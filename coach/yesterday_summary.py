"""
coach/yesterday_summary.py

Layer 3 consumer: generates a cached \"Yesterday summary\" bundle.

Flow (mirrors coach/morning_brief.py):
1. Determine the active IST cycle date.
2. If strict recap summary is missing, clear cached fields and return.
3. Ensure Layer 2 narrative is present for today (best-effort inline regen if stale/missing).
4. Run Layer 3 yesterday-summary prompt against narrative + CoachInputPacket.
5. Persist output into UserUnifiedProfile cache fields.
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

log = logging.getLogger(__name__)

_OFFLINE_YESTERDAY_SUMMARY = {
    "weekly_trend": "Your summary is being prepared. Check back in a moment.",
    "yesterday_stress": "I don't have yesterday’s stress details yet.",
    "yesterday_waking_recovery": "I don't have yesterday’s waking recovery details yet.",
    "yesterday_sleep_recovery": "I don't have yesterday’s sleep recovery details yet.",
    "yesterday_adherence": "I don't have yesterday’s plan adherence details yet.",
}


async def clear_yesterday_summary_uup(
    session,
    user_id: uuid_mod.UUID,
    cycle_ist: date,
) -> None:
    """Clear cached yesterday-summary fields for this cycle."""
    from sqlalchemy import select
    import api.db.schema as db

    res = await session.execute(
        select(db.UserUnifiedProfile).where(db.UserUnifiedProfile.user_id == user_id)
    )
    uup = res.scalar_one_or_none()
    now_utc = datetime.now(UTC)

    if uup is None:
        uup = db.UserUnifiedProfile(
            id=uuid_mod.uuid4(),
            user_id=user_id,
            yesterday_summary_weekly_trend=None,
            yesterday_summary_stress=None,
            yesterday_summary_recovery=None,
            yesterday_summary_waking_recovery=None,
            yesterday_summary_sleep_recovery=None,
            yesterday_summary_adherence=None,
            yesterday_summary_generated_for=cycle_ist,
            yesterday_summary_generated_at=now_utc,
        )
        res = session.add(uup)
        if inspect.isawaitable(res):
            await res
    else:
        uup.yesterday_summary_weekly_trend = None
        uup.yesterday_summary_stress = None
        uup.yesterday_summary_recovery = None
        uup.yesterday_summary_waking_recovery = None
        uup.yesterday_summary_sleep_recovery = None
        uup.yesterday_summary_adherence = None
        uup.yesterday_summary_generated_for = cycle_ist
        uup.yesterday_summary_generated_at = now_utc
    await session.commit()


async def generate_yesterday_summary(
    session_factory: Callable,
    user_id: uuid_mod.UUID,
    llm_client: Optional[Any],
) -> None:
    """Generate and persist yesterday summary for the user."""
    try:
        async with session_factory() as session:
            await _run_yesterday_summary(session, user_id, llm_client)
    except Exception:
        log.exception("generate_yesterday_summary failed user=%s", user_id)


async def _run_yesterday_summary(
    session,
    user_id: uuid_mod.UUID,
    llm_client: Optional[Any],
) -> None:
    from sqlalchemy import select
    import api.db.schema as db
    from api.services.tracking_service import TrackingService

    svc = TrackingService(session, str(user_id), session_factory=None, llm_client=None)
    cycle_ist = await svc.get_current_cycle_local_date()
    recap = await svc.get_morning_recap()
    if not recap.get("summary"):
        await clear_yesterday_summary_uup(session, user_id, cycle_ist)
        log.info("yesterday_summary skipped — no strict yesterday summary user=%s", user_id)
        return

    uup_res = await session.execute(
        select(db.UserUnifiedProfile).where(db.UserUnifiedProfile.user_id == user_id)
    )
    uup = uup_res.scalar_one_or_none()

    from coach.input_builder import build_coach_input_packet
    from coach.prompt_templates import (
        build_layer2_narrative_prompt,
        build_layer3_yesterday_summary_prompt,
    )

    narrative: Optional[str] = getattr(uup, "coach_narrative", None) if uup else None
    narrative_date = getattr(uup, "coach_narrative_date", None) if uup else None
    narrative_is_fresh = (narrative_date == cycle_ist) if narrative_date is not None else False

    # Best-effort inline Layer 2 regen
    if (not narrative or not narrative_is_fresh) and llm_client is not None:
        try:
            packet = await build_coach_input_packet(session, user_id)
            sys_p, user_p = build_layer2_narrative_prompt(packet)
            raw = await asyncio.wait_for(
                asyncio.to_thread(llm_client.chat, sys_p, user_p, False),
                timeout=30.0,
            )
            narrative = (raw or "").strip() or None
            if uup is not None and narrative:
                uup.coach_narrative = narrative
                uup.coach_narrative_date = cycle_ist
                await session.commit()
                log.info("yesterday_summary: Layer 2 narrative regenerated inline user=%s", user_id)
        except Exception:
            log.exception("yesterday_summary: inline Layer 2 regen failed user=%s", user_id)

    result: Optional[dict] = None
    if llm_client is not None and narrative:
        try:
            packet = await build_coach_input_packet(session, user_id)
            sys_prompt, user_prompt = build_layer3_yesterday_summary_prompt(packet, narrative)
            raw = await asyncio.wait_for(
                asyncio.to_thread(llm_client.chat, sys_prompt, user_prompt, True),
                timeout=30.0,
            )
            result = _parse_yesterday_json(raw)
        except Exception:
            log.exception("yesterday_summary: Layer 3 LLM failed user=%s", user_id)

    if result is None:
        result = _OFFLINE_YESTERDAY_SUMMARY.copy()

    now_utc = datetime.now(UTC)
    fields = {
        "yesterday_summary_weekly_trend": result["weekly_trend"],
        "yesterday_summary_stress": result["yesterday_stress"],
        # Legacy combined field stays null on new writes; readers fall back to
        # the split columns below.
        "yesterday_summary_recovery": None,
        "yesterday_summary_waking_recovery": result["yesterday_waking_recovery"],
        "yesterday_summary_sleep_recovery": result["yesterday_sleep_recovery"],
        "yesterday_summary_adherence": result["yesterday_adherence"],
        "yesterday_summary_generated_for": cycle_ist,
        "yesterday_summary_generated_at": now_utc,
    }

    if uup is not None:
        for k, v in fields.items():
            setattr(uup, k, v)
    else:
        uup = db.UserUnifiedProfile(id=uuid_mod.uuid4(), user_id=user_id, **fields)
        session.add(uup)

    await session.commit()


def _parse_yesterday_json(raw: str) -> Optional[dict]:
    if not raw:
        return None
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\n?", "", cleaned)
    cleaned = re.sub(r"\n?```$", "", cleaned)
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except Exception:
        return None

    keys = (
        "weekly_trend",
        "yesterday_stress",
        "yesterday_waking_recovery",
        "yesterday_sleep_recovery",
        "yesterday_adherence",
    )
    if not all(k in obj for k in keys):
        # Back-compat: if the LLM still returned the old single-recovery
        # schema, split it into the two new fields so callers never see a
        # half-populated response.
        legacy_keys = (
            "weekly_trend",
            "yesterday_stress",
            "yesterday_recovery",
            "yesterday_adherence",
        )
        if all(k in obj for k in legacy_keys):
            combined = str(obj.get("yesterday_recovery", ""))[:1200]
            return {
                "weekly_trend": str(obj.get("weekly_trend", ""))[:1200],
                "yesterday_stress": str(obj.get("yesterday_stress", ""))[:1200],
                "yesterday_waking_recovery": combined,
                "yesterday_sleep_recovery": combined,
                "yesterday_adherence": str(obj.get("yesterday_adherence", ""))[:1200],
            }
        return None
    # Safety caps
    return {
        "weekly_trend": str(obj.get("weekly_trend", ""))[:1200],
        "yesterday_stress": str(obj.get("yesterday_stress", ""))[:1200],
        "yesterday_waking_recovery": str(obj.get("yesterday_waking_recovery", ""))[:1200],
        "yesterday_sleep_recovery": str(obj.get("yesterday_sleep_recovery", ""))[:1200],
        "yesterday_adherence": str(obj.get("yesterday_adherence", ""))[:1200],
    }

