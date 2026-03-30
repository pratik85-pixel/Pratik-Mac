"""
api/routers/admin.py

One-shot admin / debug endpoints.

POST /admin/force-coach-refresh/{user_id}
    Forces a full Phase 4 pipeline refresh for a single user:
      1. Clears stale-guards so nothing is skipped (coach_narrative_date,
         morning_brief_generated_for).
      2. Builds CoachInputPacket and runs Layer 2 narrative LLM call.
      3. Generates morning brief via Layer 3.
      4. Regenerates today's plan (+ brief + avoid_items).

    Safe to call multiple times — just overwrites whatever was there.
    Does NOT affect any other user or any shared state.

USE: testing / QA only. Not exposed in production docs.
"""

from __future__ import annotations

import logging
import uuid as uuid_mod
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.database import get_db
from api.db import schema as db
from api.utils import parse_uuid

log = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/force-coach-refresh/{user_id}", status_code=200)
async def force_coach_refresh(
    user_id: str,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict:
    """
    Force a full Layer 2 → Layer 3 pipeline refresh for one user.
    Returns a summary of what was generated.
    """
    uid = parse_uuid(user_id)
    if uid is None:
        raise HTTPException(422, f"Invalid user_id: {user_id!r}")

    llm_client = getattr(getattr(request, "app", None), "state", None)
    if llm_client is not None:
        llm_client = getattr(llm_client, "llm_client", None)

    result: dict = {"user_id": user_id, "steps": {}}

    # ── Step 0: Clear freshness guards so nothing gets skipped ───────────────
    uup_res = await session.execute(
        select(db.UserUnifiedProfile).where(db.UserUnifiedProfile.user_id == uid)
    )
    uup = uup_res.scalar_one_or_none()
    if uup is not None:
        uup.coach_narrative_date = None
        uup.morning_brief_generated_for = None
        await session.commit()
    result["steps"]["guards_cleared"] = True

    # ── Step 1: Layer 2 — build packet + run narrative LLM call ─────────────
    try:
        from coach.input_builder import build_coach_input_packet
        from coach.prompt_templates import build_layer2_narrative_prompt
        from tracking.cycle_boundaries import local_today

        today_ist: date = local_today()
        packet = await build_coach_input_packet(session, uid)
        sys_p, user_p = build_layer2_narrative_prompt(packet)

        if llm_client is not None:
            raw = llm_client.chat(sys_p, user_p)
            narrative = (raw or "").strip()
        else:
            # Offline fallback — import from nightly_rebuild
            from jobs.nightly_rebuild import _fallback_layer2_narrative
            narrative = _fallback_layer2_narrative(packet)

        # Persist narrative
        uup_res2 = await session.execute(
            select(db.UserUnifiedProfile).where(db.UserUnifiedProfile.user_id == uid)
        )
        uup = uup_res2.scalar_one_or_none()
        if uup is None:
            uup = db.UserUnifiedProfile(
                id=uuid_mod.uuid4(),
                user_id=uid,
                coach_narrative=narrative,
                coach_narrative_date=today_ist,
            )
            session.add(uup)
        else:
            uup.coach_narrative = narrative
            uup.coach_narrative_date = today_ist
            uup.coach_watch_notes = _extract_watch_bullets(narrative)
        await session.commit()

        result["steps"]["layer2_narrative"] = "ok"
        result["narrative_preview"] = narrative[:300] + "…" if len(narrative) > 300 else narrative
    except Exception as exc:
        log.exception("force_coach_refresh: layer2 failed user=%s", user_id)
        result["steps"]["layer2_narrative"] = f"error: {exc}"

    # ── Step 2: Layer 3 — morning brief ─────────────────────────────────────
    try:
        from coach.morning_brief import _run_morning_brief
        from api.db.database import AsyncSessionLocal

        await _run_morning_brief(session, uid, llm_client)
        result["steps"]["morning_brief"] = "ok"
    except Exception as exc:
        log.exception("force_coach_refresh: morning_brief failed user=%s", user_id)
        result["steps"]["morning_brief"] = f"error: {exc}"

    # ── Step 3: Plan + brief + avoid_items ───────────────────────────────────
    try:
        from api.services.plan_service import PlanService
        from api.services.model_service import ModelService

        model_svc = ModelService(db=session)
        plan_svc = PlanService(db=session, model_service=model_svc, llm_client=llm_client)
        plan_dict = await plan_svc.get_or_create_today_plan(str(uid), force_regen=True)
        result["steps"]["plan"] = "ok"
        result["plan_items"] = len(plan_dict.get("items", []))
        result["plan_day_type"] = plan_dict.get("day_type")
        result["plan_brief"] = plan_dict.get("brief")
        result["avoid_items"] = plan_dict.get("avoid_items", [])
    except Exception as exc:
        log.exception("force_coach_refresh: plan failed user=%s", user_id)
        result["steps"]["plan"] = f"error: {exc}"

    return result


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_watch_bullets(narrative: str) -> list[str]:
    """Pull bullet lines from the WATCH TODAY section of the narrative."""
    bullets: list[str] = []
    in_section = False
    for line in narrative.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("WATCH TODAY"):
            in_section = True
            continue
        if in_section:
            # Stop at next section header (all-caps word followed by nothing or colon)
            if stripped and stripped == stripped.upper() and not stripped.startswith("•"):
                break
            if stripped.startswith("•"):
                bullets.append(stripped.lstrip("• ").strip())
    return bullets
