"""
api/routers/plan.py

Plan management and check-in endpoints.

GET  /plan/today        — today's plan items (via PlanService)
GET  /plan/home-status  — Home line: anchor intention + adherence + on_track (Phase 6)
GET  /plan/week         — full week plan (session targets + schedule)
POST /plan/check-in     — submit 3-question subjective check-in
POST /plan/trigger-today — force-regenerate today's plan
"""

from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from coach.plan_replanner import compute_daily_prescription
from api.auth import UserIdDep
from api.db.database import get_db, AsyncSessionLocal
from api.db.schema import CheckIn
from api.utils import parse_uuid
from api.services.model_service import ModelService
from api.services.plan_service import PlanService
from api.services.tracking_service import TrackingService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/plan", tags=["plan"])


# ── Dependencies ───────────────────────────────────────────────────────────────

async def _model_svc(db: AsyncSession = Depends(get_db)) -> ModelService:
    return ModelService(db=db)


async def _tracking_svc_plan(
    request: Request,
    user_id: UserIdDep,
    db: AsyncSession = Depends(get_db),
) -> TrackingService:
    llm_client = getattr(request.app.state, "llm_client", None)
    return TrackingService(
        db_session=db,
        user_id=user_id,
        session_factory=AsyncSessionLocal,
        llm_client=llm_client,
    )


# ── Request / response models ──────────────────────────────────────────────────

class CheckInRequest(BaseModel):
    reactivity: int = Field(..., ge=1, le=5, description="1 (poor) – 5 (excellent)")
    focus:      int = Field(..., ge=1, le=5)
    recovery:   int = Field(..., ge=1, le=5)


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/today")
async def today_plan(
    request: Request,
    user_id:    UserIdDep,
    model_svc:  ModelService     = Depends(_model_svc),
    db:         AsyncSession     = Depends(get_db),
    track_svc:  TrackingService  = Depends(_tracking_svc_plan),
) -> dict:
    """
    Return today's plan items for the user.
    Loads from DB if already generated today (IST), otherwise generates and persists.
    """
    if not await track_svc.has_strict_yesterday_summary():
        plan_svc = PlanService(
            db=db, model_service=model_svc, llm_client=getattr(request.app.state, "llm_client", None)
        )
        await plan_svc.delete_today_plan_if_exists(user_id)
        return PlanService.empty_plan_payload()
    plan_svc = PlanService(
        db=db, model_service=model_svc, llm_client=getattr(request.app.state, "llm_client", None)
    )
    return await plan_svc.get_or_create_today_plan(user_id)


@router.get("/home-status")
async def plan_home_status(
    request: Request,
    user_id:    UserIdDep,
    model_svc:  ModelService     = Depends(_model_svc),
    db:         AsyncSession     = Depends(get_db),
    track_svc:  TrackingService  = Depends(_tracking_svc_plan),
) -> dict:
    """Today's plan headline for Home (intention + adherence + on_track)."""
    if not await track_svc.has_strict_yesterday_summary():
        return PlanService.empty_home_plan_status()
    plan_svc = PlanService(
        db=db, model_service=model_svc, llm_client=getattr(request.app.state, "llm_client", None)
    )
    return await plan_svc.get_home_plan_status(user_id)


@router.get("/week")
async def week_plan(
    user_id:   UserIdDep,
    model_svc: ModelService = Depends(_model_svc),
) -> dict:
    """Return the weekly session target and schedule summary."""
    profile = await model_svc.get_profile(user_id)
    prescription = compute_daily_prescription(profile)

    return {
        "user_id":          user_id,
        "stage":            profile.stage,
        "session_duration_minutes": prescription.session_duration,
        "preferred_window": prescription.session_window,
        "session_intensity": prescription.session_intensity,
        "readiness_score":  round(prescription.readiness_score, 1),
    }


@router.post("/check-in")
async def check_in(
    body:    CheckInRequest,
    user_id: UserIdDep,
    db:      AsyncSession = Depends(get_db),
) -> dict:
    """
    Record a 3-question subjective self-report.
    Results feed into the interoception gap calculation.
    """
    uid = parse_uuid(user_id)
    composite = round(((body.reactivity + body.focus + body.recovery) / 15.0) * 100)
    if uid is not None:
        row = CheckIn(
            user_id    = uid,
            reactivity = body.reactivity,
            focus      = body.focus,
            recovery   = body.recovery,
        )
        db.add(row)
        await db.commit()

    return {
        "user_id":         user_id,
        "composite_score": composite,
        "message": (
            "Thanks — your check-in is stored. "
            "We'll compare this to your HRV readings to sharpen your profile."
        ),
    }


@router.post("/trigger-today")
async def trigger_today_plan(
    request: Request,
    user_id:    UserIdDep,
    model_svc:  ModelService     = Depends(_model_svc),
    db:         AsyncSession     = Depends(get_db),
    track_svc:  TrackingService  = Depends(_tracking_svc_plan),
) -> dict:
    """
    Force-regenerate today's plan for the user.
    Called by the frontend's 'Plan My Day' button.
    Returns the same payload as GET /plan/today.
    """
    if not await track_svc.has_strict_yesterday_summary():
        plan_svc = PlanService(
            db=db, model_service=model_svc, llm_client=getattr(request.app.state, "llm_client", None)
        )
        await plan_svc.delete_today_plan_if_exists(user_id)
        return {"user_id": user_id, "triggered": False, **PlanService.empty_plan_payload()}
    plan_svc = PlanService(
        db=db, model_service=model_svc, llm_client=getattr(request.app.state, "llm_client", None)
    )
    result = await plan_svc.get_or_create_today_plan(user_id, force_regen=True)
    return {"user_id": user_id, "triggered": True, **result}


@router.patch("/items/{slug}/complete")
async def complete_plan_item(
    slug:      str,
    user_id:   UserIdDep,
    model_svc: ModelService = Depends(_model_svc),
    db:        AsyncSession = Depends(get_db),
) -> dict:
    """
    Mark a plan item as complete by its activity slug.
    Sets has_evidence=True, recalculates adherence_pct, persists the change.
    """
    plan_svc = PlanService(db=db, model_service=model_svc)
    updated = await plan_svc.complete_plan_item(user_id, slug)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Plan item '{slug}' not found in today's plan")
    return {"slug": slug, "completed": True}
