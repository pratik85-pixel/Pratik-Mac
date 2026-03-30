"""
coach/morning_brief.py

Stream 4 — Morning brief generator (Phase 4 architecture).

Layer 3 consumer: reads UUP.coach_narrative (Layer 2) and runs a Layer 3
morning-brief prompt template to produce the day assessment.

Flow
----
1. Skip if brief is already fresh for today_ist.
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
  "day_state":      "green" | "yellow" | "red",
  "day_confidence": "high"  | "medium" | "low",
  "brief_text":     str,   -- 2–3 line plain English summary
  "evidence":       str,   -- key data signals that drove the assessment
  "one_action":     str    -- single most important thing for the user today
}
"""

from __future__ import annotations

import json
import logging
import re
import uuid as uuid_mod
from datetime import UTC, date, datetime
from typing import Any, Callable, Optional

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
    today_ist: date,
) -> None:
    """
    Persist an empty morning brief + clear UUP plan snippets when there is no
    strict DailyStressSummary row for the recap day (band not worn / no valid day).
    Sets morning_brief_generated_for=today_ist so GET /coach/morning-brief is not stale.
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
        if empty_brief and empty_plan and uup.morning_brief_generated_for == today_ist:
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
            morning_brief_generated_for=today_ist,
            morning_brief_generated_at=now_utc,
            suggested_plan_json=[],
            avoid_items_json=[],
            plan_generated_for_date=None,
        )
        session.add(uup)
    else:
        uup.morning_brief_text = None
        uup.morning_brief_day_state = None
        uup.morning_brief_day_confidence = None
        uup.morning_brief_evidence = None
        uup.morning_brief_one_action = None
        uup.morning_brief_generated_for = today_ist
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
    from tracking.cycle_boundaries import local_today

    today_ist = local_today()

    svc = TrackingService(session, str(user_id), session_factory=None, llm_client=None)
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

    # Skip if brief is already fresh for today
    if uup and uup.morning_brief_generated_for == today_ist:
        already_populated = any([
            uup.morning_brief_day_state,
            uup.morning_brief_day_confidence,
            uup.morning_brief_text,
            uup.morning_brief_evidence,
            uup.morning_brief_one_action,
        ])
        if already_populated:
            log.debug("morning_brief already fresh for today user=%s", user_id)
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
            raw = llm_client.chat(sys_p, user_p, json_mode=False)
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
    if llm_client is not None and narrative:
        try:
            packet = await build_coach_input_packet(session, user_id)
            sys_prompt, user_prompt = build_layer3_morning_brief_prompt(packet, narrative)
            raw = llm_client.chat(sys_prompt, user_prompt)
            result = _parse_brief_json(raw)
        except Exception:
            log.exception("morning_brief: Layer 3 LLM failed user=%s", user_id)

    # Step 3: Offline/test fallback — narrative missing and no LLM
    if result is None:
        result = _OFFLINE_BRIEF.copy()
        log.info("morning_brief: using offline fallback user=%s", user_id)

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

    if obj["day_state"] not in ("green", "yellow", "red"):
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


