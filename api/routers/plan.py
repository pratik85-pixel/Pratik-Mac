"""
api/routers/plan.py

Plan management and check-in endpoints.

GET  /plan/today        — today's plan items (via PlanService)
GET  /plan/week         — full week plan (session targets + schedule)
POST /plan/check-in     — submit 3-question subjective check-in
POST /plan/trigger-today — force-regenerate today's plan
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from coach.plan_replanner import compute_daily_prescription
from api.db.database import get_db
from api.db.schema import CheckIn
from api.utils import parse_uuid
from api.services.model_service import ModelService
from api.services.plan_service import PlanService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/plan", tags=["plan"])


# ── Dependencies ───────────────────────────────────────────────────────────────

async def _user_id(x_user_id: Annotated[str, Header()]) -> str:
    if not x_user_id:
        raise HTTPException(status_code=401, detail="X-User-Id header required")
    return x_user_id

async def _model_svc(db: AsyncSession = Depends(get_db)) -> ModelService:
    return ModelService(db=db)


# ── Request / response models ──────────────────────────────────────────────────

class CheckInRequest(BaseModel):
    reactivity: int = Field(..., ge=1, le=5, description="1 (poor) – 5 (excellent)")
    focus:      int = Field(..., ge=1, le=5)
    recovery:   int = Field(..., ge=1, le=5)


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/today")
async def today_plan(
    user_id:   str          = Depends(_user_id),
    model_svc: ModelService = Depends(_model_svc),
    db:        AsyncSession = Depends(get_db),
) -> dict:
    """
    Return today's plan items for the user.
    Loads from DB if already generated today (IST), otherwise generates and persists.
    """
    plan_svc = PlanService(db=db, model_service=model_svc)
    return await plan_svc.get_or_create_today_plan(user_id)


@router.get("/week")
async def week_plan(
    user_id:   str          = Depends(_user_id),
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
        "load_score":       prescription.load_score,
    }


@router.post("/check-in")
async def check_in(
    body:    CheckInRequest,
    user_id: str          = Depends(_user_id),
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
    user_id:   str          = Depends(_user_id),
    model_svc: ModelService = Depends(_model_svc),
    db:        AsyncSession = Depends(get_db),
) -> dict:
    """
    Force-regenerate today's plan for the user.
    Called by the frontend's 'Plan My Day' button.
    Returns the same payload as GET /plan/today.
    """
    plan_svc = PlanService(db=db, model_service=model_svc)
    result = await plan_svc.get_or_create_today_plan(user_id, force_regen=True)
    return {"user_id": user_id, "triggered": True, **result}
