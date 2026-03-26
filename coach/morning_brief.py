"""
coach/morning_brief.py

Stream 4 — Morning brief generator.

Generates a single-screen day assessment for the user, cached when the morning
reset runs: either sleep → background after overnight wear (Scenario A, with
nap-safety gates), or the forced no–overnight-wear path after the daily anchor
(Scenario B — first background ingest after anchor with no band in the prior
inter-anchor window). This keeps the brief ready when the user opens the app
without generating on every app open.

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
  "brief_text":     str,   -- 1–2 sentence plain English summary
  "evidence":       str,   -- key data signals that drove the assessment
  "one_action":     str    -- single most important thing for the user today
}

Deterministic fallback (no LLM)
--------------------------------
Uses yesterday readiness + recent trajectory + coverage to produce a
2–3 line brief and a strain target.
"""

from __future__ import annotations

import json
import logging
import re
import uuid as uuid_mod
from datetime import UTC, date, datetime, timedelta
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)

# ── LLM system prompt ─────────────────────────────────────────────────────────

_SYSTEM = """\
You are ZenFlow's morning coach. Your job is to write a brief, warm, \
data-grounded day assessment that the user will read the moment they wake up.

Rules
-----
- day_state  : "green" | "yellow" | "red"
- day_confidence: "high" if ≥4 band days available in last 7, else "medium" or "low"
- brief_text : STRICTLY 2–3 lines. Must include:
  1) type of day (green/yellow/red),
  2) yesterday readiness score,
  3) today's strain target and what it implies.
- evidence   : trajectory-based only (past days trend), 1–2 sentences.
- one_action : One clear, doable action for today (≤15 words). No disclaimers.
- Never use the phrase "opening balance". Use readiness language only.

Output ONLY valid JSON matching this schema — no prose, no markdown fences:
{
  "day_state":      "green"|"yellow"|"red",
  "day_confidence": "high"|"medium"|"low",
  "brief_text":     "...",
  "evidence":       "...",
  "one_action":     "..."
}
"""

# ── Main entry point ─────────────────────────────────────────────────────────

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
            await _generate_and_store(session, user_id, llm_client)
    except Exception:
        log.exception("generate_morning_brief failed user=%s", user_id)


# ── Core logic ────────────────────────────────────────────────────────────────

async def _generate_and_store(
    session,
    user_id: uuid_mod.UUID,
    llm_client: Optional[Any],
) -> None:
    from zoneinfo import ZoneInfo
    from sqlalchemy import select
    import api.db.schema as db
    from coach.data_assembler import assemble_for_user

    IST = ZoneInfo("Asia/Kolkata")
    today_ist = datetime.now(IST).date()

    # Skip if brief is already fresh for today
    uup_res = await session.execute(
        select(db.UserUnifiedProfile).where(db.UserUnifiedProfile.user_id == user_id)
    )
    uup = uup_res.scalar_one_or_none()
    if uup and uup.morning_brief_generated_for == today_ist:
        log.debug("morning_brief already fresh for today user=%s", user_id)
        return

    # Assemble context
    ctx = await assemble_for_user(session, user_id)

    # Coach watch notes from UUP
    watch_notes: list[str] = (uup.coach_watch_notes or []) if uup else []
    band_days = (uup.band_days_worn_last7 or 0) if uup else 0

    # Build gap-annotated 7-day trajectory string
    traj_str = _build_trajectory_prompt(ctx.daily_trajectory, today_ist)

    # Derive yesterday readiness/day state from explicit IST yesterday row.
    yesterday_ist = today_ist - timedelta(days=1)
    yesterday_row = _find_trajectory_row_for_date(ctx.daily_trajectory, yesterday_ist)
    latest_day = ctx.daily_trajectory[-1] if ctx.daily_trajectory else {}
    source_row = yesterday_row or latest_day
    yesterday_readiness = _readiness_from_net_balance(source_row.get("net_balance"))
    day_state = str(source_row.get("day_type") or _day_state_from_readiness(yesterday_readiness))
    strain_target = _strain_target_from_state_and_readiness(day_state, yesterday_readiness)

    # Assemble user prompt
    user_prompt = _build_user_prompt(
        today=today_ist,
        traj_str=traj_str,
        day_state=day_state,
        yesterday_readiness=yesterday_readiness,
        strain_target=strain_target,
        watch_notes=watch_notes,
        band_days=band_days,
    )

    # Try LLM
    result: Optional[dict] = None
    if llm_client is not None:
        try:
            raw = llm_client.chat(_SYSTEM, user_prompt)
            result = _parse_brief_json(raw)
        except Exception:
            log.exception("morning_brief LLM call failed user=%s — using fallback", user_id)

    if result is None:
        result = _deterministic_brief(
            ctx.daily_trajectory,
            band_days,
            day_state=day_state,
            yesterday_readiness=yesterday_readiness,
            strain_target=strain_target,
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
    else:
        # No UUP row yet — create a minimal one just for the brief fields
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


# ── Prompt helpers ────────────────────────────────────────────────────────────

def _build_trajectory_prompt(trajectory: list[dict], today_ist: date) -> str:
    """
    Return a 7-day annotated trajectory string.
    Gaps (no band data) are explicitly labelled.
    """
    from datetime import timedelta

    all_dates = {today_ist - timedelta(days=i) for i in range(1, 8)}
    available_dates = {
        _parse_date(row.get("date", ""))
        for row in trajectory
        if row.get("date")
    } - {None}
    gap_dates = all_dates - available_dates

    lines = []
    for row in trajectory:
        d = _parse_date(row.get("date", ""))
        if d is None:
            continue
        sl  = row.get("stress_load")
        wr  = row.get("waking_recovery")
        dt  = row.get("day_type", "unknown")
        sl_str = str(round(sl)) if sl is not None else "?"
        wr_str = str(round(wr)) if wr is not None else "?"
        lines.append(
            f"  {d.isoformat()}: stress={sl_str}/100, "
            f"recovery={wr_str}/100, day_type={dt}"
        )

    for gd in sorted(gap_dates):
        lines.append(f"  {gd.isoformat()}: [NO DATA — band not worn]")

    lines.sort()
    return "\n".join(lines) if lines else "  (no data available)"


def _find_trajectory_row_for_date(trajectory: list[dict], target_date: date) -> Optional[dict]:
    """Return trajectory row matching target_date (YYYY-MM-DD) if present."""
    target = target_date.isoformat()
    for row in trajectory:
        if str(row.get("date", "")).startswith(target):
            return row
    return None


def _build_user_prompt(
    *,
    today: date,
    traj_str: str,
    day_state: str,
    yesterday_readiness: int,
    strain_target: int,
    watch_notes: list[str],
    band_days: int,
) -> str:
    notes_str = "\n".join(f"  • {n}" for n in watch_notes) if watch_notes else "  • None"
    return f"""
TODAY: {today.isoformat()}
TODAY DAY TYPE: {day_state}
YESTERDAY READINESS SCORE: {yesterday_readiness}
TODAY STRAIN TARGET: {strain_target}

7-DAY TRAJECTORY (oldest → newest, IST dates):
{traj_str}

BAND DAYS WORN LAST 7: {band_days}/7

COACH WATCH NOTES (from last nightly analysis):
{notes_str}

Generate the morning brief now. Output only valid JSON.
""".strip()


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


# ── Deterministic fallback ────────────────────────────────────────────────────

def _deterministic_brief(
    trajectory: list[dict],
    band_days: int,
    *,
    day_state: str,
    yesterday_readiness: int,
    strain_target: int,
) -> dict:
    """Rule-based morning brief when LLM is unavailable."""
    state = day_state if day_state in ("green", "yellow", "red") else _day_state_from_readiness(yesterday_readiness)
    recent = trajectory[-4:] if trajectory else []
    stress_vals = [r.get("stress_load") for r in recent if r.get("stress_load") is not None]
    recov_vals = [r.get("waking_recovery") for r in recent if r.get("waking_recovery") is not None]
    trend_note = "recent trend is mixed"
    if len(stress_vals) >= 2 and len(recov_vals) >= 2:
        s_delta = float(stress_vals[-1]) - float(stress_vals[0])
        r_delta = float(recov_vals[-1]) - float(recov_vals[0])
        if r_delta >= 4 and s_delta <= 2:
            trend_note = "recovery trend improved while stress stayed controlled"
        elif s_delta >= 6:
            trend_note = "stress trended up over recent days"
        elif r_delta <= -4:
            trend_note = "recovery trended down over recent days"

    brief = (
        f"Today is a {state} day. Your readiness score of {yesterday_readiness} "
        f"supports a strain target of {strain_target}.\n"
        "Your body signal suggests this target is realistic for today."
    )
    action = (
        "Do your hardest planned block early."
        if state == "green"
        else "Keep intensity moderate and pace your sessions."
        if state == "yellow"
        else "Prioritize recovery blocks and avoid hard exertion."
    )

    # Confidence
    if band_days >= 4:
        confidence = "high"
    elif band_days >= 2:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "day_state":      state,
        "day_confidence": confidence,
        "brief_text":     brief,
        "evidence":       f"Past trajectory shows {trend_note}. {len(recent)}/4 recent days available.",
        "one_action":     action,
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_date(s: str) -> Optional[date]:
    try:
        return date.fromisoformat(s[:10])
    except (ValueError, TypeError):
        return None


def _readiness_from_net_balance(net_balance: Any) -> int:
    try:
        if net_balance is None:
            return 50
        v = ((float(net_balance) + 30.0) / 60.0) * 100.0
        return int(round(max(0.0, min(100.0, v))))
    except Exception:
        return 50


def _day_state_from_readiness(readiness: int) -> str:
    if readiness >= 70:
        return "green"
    if readiness >= 45:
        return "yellow"
    return "red"


def _strain_target_from_state_and_readiness(day_state: str, readiness: int) -> int:
    base = 70 if day_state == "green" else 55 if day_state == "yellow" else 40
    adj = 8 if readiness >= 80 else 4 if readiness >= 65 else 0 if readiness >= 45 else -6
    return int(max(30, min(90, base + adj)))
