"""
coach/morning_brief.py

Stream 4 — Morning brief generator (Phase 4 architecture).

Layer 3 consumer: reads UUP.coach_narrative (Layer 2) and runs a Layer 3
morning-brief prompt template to produce the day assessment.

Flow
----
1. Skip if brief is already fresh for the IST calendar day (``local_today()``).
2. If coach_narrative is missing or stale AND llm_client is available,
   trigger a Layer 2 narrative regen inline before proceeding.
3. Run Layer 3 morning-brief prompt against narrative + CoachInputPacket.
4. If narrative is unavailable and llm_client is None (offline/test),
   return a minimal static brief ("data not yet available").

Public API
----------
    await generate_morning_brief(session_factory, user_id, llm_client)

The function opens its own DB session from the factory so it can run as a
fire-and-forget asyncio.create_task() without interfering with the ingest
pipeline's live session.

LLM output schema
-----------------
{
  "day_state":      "green" | "yellow" | "relaxed" | "red",
  "day_confidence": "high"  | "medium" | "low",
  "brief_text":     str,   -- 2–3 line plain English summary
  "evidence":       str,   -- key data signals that drove the assessment
  "one_action":     str    -- single most important thing for the user today
}
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import inspect
import uuid as uuid_mod
from datetime import UTC, date, datetime
from typing import Any, Callable, Optional

from tracking.cycle_boundaries import local_today

log = logging.getLogger(__name__)

# ── Static offline brief ──────────────────────────────────────────────────────

_OFFLINE_BRIEF = {
    "day_state":      "yellow",
    "day_confidence": "low",
    "brief_text":     "Your morning brief is being prepared. Check back in a moment.",
    "evidence":       "Narrative not yet available for today.",
    "one_action":     "Put your band on and start moving — data will update shortly.",
}

# ── Main entry point ─────────────────────────────────────────────────────────

async def clear_morning_bundle_uup(
    session,
    user_id: uuid_mod.UUID,
    generated_for_day: date,
) -> None:
    """
    Persist an empty morning brief + clear UUP plan snippets when there is no
    strict DailyStressSummary row for the recap day (band not worn / no valid day).
    Sets ``morning_brief_generated_for`` to ``generated_for_day`` (typically ``local_today()``).
    """
    from sqlalchemy import select
    import api.db.schema as db

    res = await session.execute(
        select(db.UserUnifiedProfile).where(db.UserUnifiedProfile.user_id == user_id)
    )
    uup = res.scalar_one_or_none()
    now_utc = datetime.now(UTC)
    if uup is not None:
        empty_brief = (
            uup.morning_brief_text is None
            and uup.morning_brief_day_state is None
            and uup.morning_brief_day_confidence is None
            and uup.morning_brief_evidence is None
            and uup.morning_brief_one_action is None
        )
        empty_plan = not (uup.suggested_plan_json or uup.avoid_items_json)
        if empty_brief and empty_plan and uup.morning_brief_generated_for == generated_for_day:
            return
    if uup is None:
        uup = db.UserUnifiedProfile(
            id=uuid_mod.uuid4(),
            user_id=user_id,
            morning_brief_text=None,
            morning_brief_day_state=None,
            morning_brief_day_confidence=None,
            morning_brief_evidence=None,
            morning_brief_one_action=None,
            morning_brief_generated_for=generated_for_day,
            morning_brief_generated_at=now_utc,
            suggested_plan_json=[],
            avoid_items_json=[],
            plan_generated_for_date=None,
        )
        res = session.add(uup)
        if inspect.isawaitable(res):
            await res
    else:
        uup.morning_brief_text = None
        uup.morning_brief_day_state = None
        uup.morning_brief_day_confidence = None
        uup.morning_brief_evidence = None
        uup.morning_brief_one_action = None
        uup.morning_brief_generated_for = generated_for_day
        uup.morning_brief_generated_at = now_utc
        uup.suggested_plan_json = []
        uup.avoid_items_json = []
        uup.plan_generated_for_date = None
    await session.commit()


async def generate_morning_brief(
    session_factory: Callable,
    user_id: uuid_mod.UUID,
    llm_client: Optional[Any],
) -> None:
    """
    Generate and persist a morning brief for the user.

    Uses its own DB session (from session_factory) so it is safe to run as
    a fire-and-forget asyncio.create_task().
    """
    try:
        async with session_factory() as session:
            await _run_morning_brief(session, user_id, llm_client)
    except Exception:
        log.exception("generate_morning_brief failed user=%s", user_id)


# ── Core logic (Phase 4: Layer 2 → Layer 3) ──────────────────────────────────

async def _run_morning_brief(
    session,
    user_id: uuid_mod.UUID,
    llm_client: Optional[Any],
) -> None:
    from sqlalchemy import select
    import api.db.schema as db
    from api.services.tracking_service import TrackingService

    svc = TrackingService(session, str(user_id), session_factory=None, llm_client=None)
    today_ist = local_today()
    recap = await svc.get_morning_recap()
    if not recap.get("summary"):
        await clear_morning_bundle_uup(session, user_id, today_ist)
        log.info("morning_brief skipped — no strict yesterday summary user=%s", user_id)
        return

    # Load UUP
    uup_res = await session.execute(
        select(db.UserUnifiedProfile).where(db.UserUnifiedProfile.user_id == user_id)
    )
    uup = uup_res.scalar_one_or_none()

    # Skip if brief is already fresh for this IST calendar day
    if uup and uup.morning_brief_generated_for == today_ist:
        already_populated = any([
            uup.morning_brief_day_state,
            uup.morning_brief_day_confidence,
            uup.morning_brief_text,
            uup.morning_brief_evidence,
            uup.morning_brief_one_action,
        ])
        if already_populated:
            log.debug("morning_brief already fresh for calendar day user=%s", user_id)
            return

    from coach.input_builder import build_coach_input_packet
    from coach.prompt_templates import build_layer2_narrative_prompt, build_layer3_morning_brief_prompt

    # Determine if narrative is today's
    narrative: Optional[str] = getattr(uup, "coach_narrative", None) if uup else None
    narrative_date = getattr(uup, "coach_narrative_date", None) if uup else None
    narrative_is_fresh = (narrative_date == today_ist) if narrative_date is not None else False

    # Step 1: If narrative is missing or stale and LLM is available — regen Layer 2 inline
    if (not narrative or not narrative_is_fresh) and llm_client is not None:
        try:
            packet = await build_coach_input_packet(session, user_id)
            sys_p, user_p = build_layer2_narrative_prompt(packet)
            raw = await asyncio.wait_for(
                asyncio.to_thread(llm_client.chat, sys_p, user_p, False),
                timeout=30.0,
            )
            narrative = (raw or "").strip() or None
            # Persist the fresh narrative immediately
            if uup is not None and narrative:
                uup.coach_narrative = narrative
                uup.coach_narrative_date = today_ist
                await session.commit()
                log.info("morning_brief: Layer 2 narrative regenerated inline user=%s", user_id)
        except Exception:
            log.exception("morning_brief: inline Layer 2 regen failed user=%s", user_id)

    # Step 2: Run Layer 3 morning-brief prompt against narrative
    result: Optional[dict] = None
    sys_prompt: Optional[str] = None
    user_prompt: Optional[str] = None
    if llm_client is not None and narrative:
        try:
            packet = await build_coach_input_packet(session, user_id)
            sys_prompt, user_prompt = build_layer3_morning_brief_prompt(packet, narrative)
            raw = await asyncio.wait_for(
                asyncio.to_thread(llm_client.chat, sys_prompt, user_prompt, True),
                timeout=30.0,
            )
            result = _parse_brief_json(raw)
        except Exception:
            log.exception("morning_brief: Layer 3 LLM failed user=%s", user_id)

    # Step 3: Offline/test fallback — narrative missing and no LLM
    if result is None:
        result = _OFFLINE_BRIEF.copy()
        log.info("morning_brief: using offline fallback user=%s", user_id)

    expected_day_state = _expected_day_state_from_recap_summary(recap.get("summary"))
    result = _retry_and_enforce_day_state_parity(
        result=result,
        expected_day_state=expected_day_state,
        llm_client=llm_client,
        sys_prompt=sys_prompt,
        user_prompt=user_prompt,
        user_id=user_id,
    )

    # Persist
    now_utc = datetime.now(UTC)
    fields = {
        "morning_brief_text":           result["brief_text"],
        "morning_brief_day_state":      result["day_state"],
        "morning_brief_day_confidence": result["day_confidence"],
        "morning_brief_evidence":       result["evidence"],
        "morning_brief_one_action":     result["one_action"],
        "morning_brief_generated_for":  today_ist,
        "morning_brief_generated_at":   now_utc,
    }

    if uup is not None:
        for k, v in fields.items():
            setattr(uup, k, v)
        # Clear plan brief cache so the next /plan/today call regenerates a
        # fresh Layer 3 plan brief that doesn't duplicate the morning brief.
        uup.plan_brief_text = None
    else:
        uup = db.UserUnifiedProfile(
            id=uuid_mod.uuid4(),
            user_id=user_id,
            **fields,
        )
        session.add(uup)

    await session.commit()
    log.info(
        "morning_brief stored user=%s state=%s confidence=%s",
        user_id, result["day_state"], result["day_confidence"],
    )


# ── Trajectory helpers (used by callers outside this module) ─────────────────

def _find_trajectory_row_for_date(trajectory: list[dict], target_date: date) -> Optional[dict]:
    """Return trajectory row matching target_date (YYYY-MM-DD) if present."""
    target = target_date.isoformat()
    for row in trajectory:
        if str(row.get("date", "")).startswith(target):
            return row
    return None


# ── JSON parser ───────────────────────────────────────────────────────────────

def _parse_brief_json(raw: str) -> Optional[dict]:
    """Parse the JSON object from an LLM response. Returns None on failure."""
    cleaned = re.sub(r"```(?:json)?", "", raw).strip().strip("`").strip()
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not m:
        log.warning("morning_brief: no JSON object in LLM output")
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        log.warning("morning_brief: JSON parse error: %s", exc)
        return None

    # Validate required fields
    for key in ("day_state", "day_confidence", "brief_text", "evidence", "one_action"):
        if key not in obj:
            log.warning("morning_brief: missing key %s in LLM output", key)
            return None

    if obj["day_state"] not in ("green", "yellow", "relaxed", "red"):
        obj["day_state"] = "yellow"
    if obj["day_confidence"] not in ("high", "medium", "low"):
        obj["day_confidence"] = "medium"

    return {
        "day_state":      obj["day_state"],
        "day_confidence": obj["day_confidence"],
        "brief_text":     str(obj["brief_text"])[:500],
        "evidence":       str(obj["evidence"])[:500],
        "one_action":     str(obj["one_action"])[:200],
    }


def _expected_day_state_from_recap_summary(summary: Optional[dict]) -> Optional[str]:
    """
    Deterministic day-state from strict yesterday recap values.
    Returns None when required inputs are unavailable.
    """
    if not isinstance(summary, dict):
        return None
    try:
        stress_raw = summary.get("stress_load_score")
        waking = summary.get("waking_recovery_score")
        sleep = summary.get("sleep_recovery_score")
        if stress_raw is None:
            return None
        from tracking.plan_readiness_contract import compute_composite_readiness, day_type_from_readiness

        readiness = compute_composite_readiness(
            waking_recovery=float(waking) if waking is not None else None,
            sleep_recovery=float(sleep) if sleep is not None else None,
            stress_load_0_10=float(stress_raw) / 10.0,
        )
        if readiness is None:
            return None
        return str(day_type_from_readiness(readiness))
    except Exception:
        log.debug("morning_brief: expected day_state from recap failed", exc_info=True)
        return None


def _retry_and_enforce_day_state_parity(
    *,
    result: dict,
    expected_day_state: Optional[str],
    llm_client: Optional[Any],
    sys_prompt: Optional[str],
    user_prompt: Optional[str],
    user_id: uuid_mod.UUID,
) -> dict:
    """
    Enforce parity between LLM day_state and deterministic readiness day_type.
    Retry exactly once before auto-correcting.
    """
    if expected_day_state is None:
        return result

    current = str(result.get("day_state") or "").strip().lower()
    if current == expected_day_state:
        return result

    retried = False
    if llm_client is not None and sys_prompt and user_prompt:
        retried = True
        correction = (
            "\n\nCORRECTION_CONSTRAINT:\n"
            f"- day_state MUST be exactly \"{expected_day_state}\".\n"
            "- day_state is derived from YESTERDAY_ROW only.\n"
            "- Return valid JSON with the same schema keys."
        )
        try:
            raw_retry = llm_client.chat(sys_prompt, user_prompt + correction)
            retry_result = _parse_brief_json(raw_retry)
            if retry_result is not None:
                result = retry_result
        except Exception:
            log.exception("morning_brief: parity retry failed user=%s", user_id)

    current_after_retry = str(result.get("day_state") or "").strip().lower()
    if current_after_retry != expected_day_state:
        log.warning(
            "morning_brief day_state mismatch user=%s expected=%s got=%s retried=%s; auto-correcting",
            user_id,
            expected_day_state,
            current_after_retry or "none",
            retried,
        )
        corrected = dict(result)
        corrected["day_state"] = expected_day_state
        return corrected

    return result


