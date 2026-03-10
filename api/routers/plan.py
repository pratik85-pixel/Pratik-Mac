"""
api/routers/plan.py

Plan management and check-in endpoints.

GET  /plan/today        — today's recommended session + timing
GET  /plan/week         — full week plan (session targets + schedule)
POST /plan/check-in     — submit 3-question subjective check-in
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, UTC
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select, func as sqlfunc

from coach.plan_replanner import compute_daily_prescription
from sessions.session_prescriber import (
    PRF_FOUND, PRF_UNKNOWN, PRF_CONFIRMED, prescribe_session,
)
from api.db.database import get_db
from api.db.schema import CheckIn, PersonalModel as PersonalModelRow, Session as SessionRow
from api.utils import parse_uuid
from api.services.model_service import ModelService

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
    Return today's prescribed session for the user.

    Includes:
    - `prescription`: load_score, session_type, reason_tag, timing window
    - `session`: practice_type, pacer config, duration, tier
    """
    fp      = await model_svc.get_fingerprint(user_id)
    profile = await model_svc.get_profile(user_id)

    if fp is None:
        from model.baseline_builder import PersonalFingerprint
        fp = PersonalFingerprint()

    prescription = compute_daily_prescription(profile)

    # Load PRF status + bpm from PersonalModel  ─────────────────────────────
    uid = parse_uuid(user_id)
    prf_status_val: str            = PRF_UNKNOWN
    stored_prf_bpm: Optional[float] = None
    total_sessions: int             = 0

    if uid is not None:
        pm_res = await db.execute(
            select(PersonalModelRow).where(PersonalModelRow.user_id == uid)
        )
        pm_row = pm_res.scalar_one_or_none()
        if pm_row is not None and pm_row.prf_status:
            prf_status_val = pm_row.prf_status
            stored_prf_bpm = pm_row.prf_bpm

        count_res = await db.execute(
            select(sqlfunc.count(SessionRow.id)).where(
                SessionRow.user_id == uid,
                SessionRow.context == "session",
            )
        )
        total_sessions = count_res.scalar_one() or 0

    practice = prescribe_session(
        stage                    = profile.stage,
        prf_status               = prf_status_val,
        stored_prf_bpm           = stored_prf_bpm,
        load_score               = prescription.load_score,
        session_type             = prescription.session_type,
        total_sessions_completed = total_sessions,
    )

    return {
        "user_id": user_id,
        "prescription": {
            "load_score":     prescription.load_score,
            "session_intensity": prescription.session_intensity,
            "session_type":   prescription.session_type,
            "reason_tag":     prescription.reason_tag,
            "session_window": prescription.session_window,
            "session_duration_minutes": prescription.session_duration,
            "stage":          profile.stage,
            "practice_type":  prescription.practice_type,
        },
        "session": practice.to_dict(),
    }


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
