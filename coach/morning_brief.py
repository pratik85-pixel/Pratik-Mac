"""
coach/morning_brief.py

Stream 4 — Morning brief generator.

Generates a single-screen day assessment for the user, cached at the moment
the band transitions from sleep → background (i.e. first wakeup detection).
This means the brief is ready when the user opens the app — not generated
on app open, which would add latency.

Public API
----------
    await generate_morning_brief(session_factory, user_id, opening_balance, llm_client)

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
avg net_balance over available trajectory days + band coverage count → rule map.
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
- day_state  : "green" (surplus), "yellow" (balanced/caution), "red" (debt/rest)
- day_confidence: "high" if ≥4 band days available in last 7, else "medium" or "low"
- brief_text : 1–2 sentences. Plain Indian English. Encouraging tone. Cite one real number.
- evidence   : 1–2 sentences. Specific data signals that drove the assessment.
- one_action : One clear, doable action for today (≤15 words). No disclaimers.

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
    opening_balance: float,
    llm_client: Optional[Any],
) -> None:
    """
    Generate and persist a morning brief for the user.

    Uses its own DB session (from session_factory) so it is safe to run as
    a fire-and-forget asyncio.create_task().
    """
    try:
        async with session_factory() as session:
            await _generate_and_store(session, user_id, opening_balance, llm_client)
    except Exception:
        log.exception("generate_morning_brief failed user=%s", user_id)


# ── Core logic ────────────────────────────────────────────────────────────────

async def _generate_and_store(
    session,
    user_id: uuid_mod.UUID,
    opening_balance: float,
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

    # Sleep recovery efficiency from most recent trajectory day
    sleep_eff: Optional[str] = None
    if ctx.daily_trajectory:
        latest = ctx.daily_trajectory[-1]
        sleep_eff = latest.get("sleep_recovery_efficiency") or latest.get("day_type")

    # Assemble user prompt
    user_prompt = _build_user_prompt(
        today=today_ist,
        opening_balance=opening_balance,
        traj_str=traj_str,
        sleep_eff=sleep_eff,
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
        result = _deterministic_brief(ctx.daily_trajectory, band_days)

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
        nb  = row.get("net_balance")
        sl  = row.get("stress_load")
        wr  = row.get("waking_recovery")
        dt  = row.get("day_type", "unknown")
        nb_str = f"{nb:+.1f}" if nb is not None else "?"
        sl_str = str(round(sl)) if sl is not None else "?"
        wr_str = str(round(wr)) if wr is not None else "?"
        lines.append(
            f"  {d.isoformat()}: net_balance={nb_str}, stress={sl_str}/100, "
            f"recovery={wr_str}/100, day_type={dt}"
        )

    for gd in sorted(gap_dates):
        lines.append(f"  {gd.isoformat()}: [NO DATA — band not worn]")

    lines.sort()
    return "\n".join(lines) if lines else "  (no data available)"


def _build_user_prompt(
    *,
    today: date,
    opening_balance: float,
    traj_str: str,
    sleep_eff: Optional[str],
    watch_notes: list[str],
    band_days: int,
) -> str:
    notes_str = "\n".join(f"  • {n}" for n in watch_notes) if watch_notes else "  • None"
    return f"""
TODAY: {today.isoformat()}
OPENING BALANCE (carry-forward from last night): {opening_balance:+.1f}
SLEEP / RECOVERY EFFICIENCY (last night): {sleep_eff or 'Unknown'}

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

def _deterministic_brief(trajectory: list[dict], band_days: int) -> dict:
    """Rule-based morning brief when LLM is unavailable."""
    nb_values = [
        row["net_balance"]
        for row in trajectory
        if row.get("net_balance") is not None
    ]
    avg_nb = sum(nb_values) / len(nb_values) if nb_values else 0.0
    days_available = len(nb_values)

    # State
    if avg_nb >= 10.0:
        state = "green"
        brief = (
            f"Your last {days_available} days average a net balance of {avg_nb:+.1f} — "
            "you're in a good place. Keep the morning session going."
        )
        action = "Start with a 10-minute breathing session."
    elif avg_nb >= -20.0:
        state = "yellow"
        brief = (
            f"Average net balance is {avg_nb:+.1f} over {days_available} days — "
            "balanced, but keep the easy wins coming."
        )
        action = "One short breathing or stretching session today."
    else:
        state = "red"
        brief = (
            f"Net balance has been {avg_nb:+.1f} over {days_available} days — "
            "your body needs recovery today."
        )
        action = "5 minutes of breathing only — no hard training today."

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
        "evidence":       f"{days_available}/7 days of data available, avg net_balance {avg_nb:+.1f}.",
        "one_action":     action,
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_date(s: str) -> Optional[date]:
    try:
        return date.fromisoformat(s[:10])
    except (ValueError, TypeError):
        return None
