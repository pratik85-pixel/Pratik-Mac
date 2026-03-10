"""
api/routers/user.py

User profile, archetype, and habits endpoints.

GET  /user/profile            — full user profile (name, level, archetype)
GET  /user/fingerprint        — physiological fingerprint summary
GET  /user/archetype          — current archetype + NS profile
GET  /user/habits             — lifestyle habits profile
PUT  /user/habits             — update lifestyle habits
"""

from __future__ import annotations

import uuid
import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.database import get_db
from api.db.schema import User, UserHabits
from api.services.model_service import ModelService
from api.utils import parse_uuid

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/user", tags=["user"])


# ── Dependencies ───────────────────────────────────────────────────────────────

async def _user_id(x_user_id: Annotated[str, Header()]) -> str:
    if not x_user_id:
        raise HTTPException(status_code=401, detail="X-User-Id header required")
    return x_user_id

async def _model_svc(db: AsyncSession = Depends(get_db)) -> ModelService:
    return ModelService(db=db)


# ── Request / response models ──────────────────────────────────────────────────

class HabitsUpdate(BaseModel):
    name:               Optional[str]       = None  # used to create/update the user row
    movement_enjoyed:   Optional[list[str]] = None
    exercise_frequency: Optional[str]       = None
    alcohol:            Optional[str]       = None
    caffeine:           Optional[str]       = None
    smoking:            Optional[str]       = None
    sleep_schedule:     Optional[str]       = None
    typical_day:        Optional[str]       = None
    stress_drivers:     Optional[list[str]] = None
    decompress_via:     Optional[list[str]] = None
    goal:               Optional[str]       = None  # onboarding goal, stored in onboarding JSON


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/profile")
async def get_profile(
    user_id:   str          = Depends(_user_id),
    model_svc: ModelService = Depends(_model_svc),
) -> dict:
    """Return user identity, training level, and current archetype."""
    user: Optional[User] = await model_svc.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")

    return {
        "user_id":                user_id,
        "name":                   user.name,
        "training_level":         user.training_level,
        "archetype_primary":      user.archetype_primary,
        "archetype_secondary":    user.archetype_secondary,
        "archetype_confidence":   user.archetype_confidence,
        "archetype_updated_at":   user.archetype_updated_at.isoformat() if user.archetype_updated_at else None,
        "member_since":           user.created_at.isoformat() if user.created_at else None,
    }


@router.get("/fingerprint")
async def get_fingerprint(
    user_id:   str          = Depends(_user_id),
    model_svc: ModelService = Depends(_model_svc),
) -> dict:
    """Return the current physiological fingerprint summary (safe for display)."""
    fp = await model_svc.get_fingerprint(user_id)
    if fp is None:
        raise HTTPException(status_code=404, detail="no fingerprint yet — complete at least one session")

    return {
        "rmssd_floor_ms":          fp.rmssd_floor,
        "rmssd_ceiling_ms":        fp.rmssd_ceiling,
        "rmssd_morning_avg_ms":    fp.rmssd_morning_avg,
        "coherence_floor":         fp.coherence_floor,
        "coherence_trainability":  fp.coherence_trainability,
        "recovery_arc_mean_hours": fp.recovery_arc_mean_hours,
        "stress_peak_hour":        fp.stress_peak_hour,
        "interoception_r":         fp.interoception_first_r,
        "best_window":             fp.best_natural_window_start,
        "overall_confidence":      fp.overall_confidence,
    }


@router.get("/archetype")
async def get_archetype(
    user_id:   str          = Depends(_user_id),
    model_svc: ModelService = Depends(_model_svc),
) -> dict:
    """
    Return the NS health profile — stage, total score, pattern labels,
    dimension breakdown, and trajectory.
    """
    profile = await model_svc.get_profile(user_id)

    return {
        "stage":             profile.stage,
        "total_score":       profile.total_score,
        "trajectory":        profile.trajectory,
        "primary_pattern":   profile.primary_pattern,
        "amplifier_pattern": profile.amplifier_pattern,
        "dimension_scores":  profile.dimension_breakdown(),
        "stage_focus":       profile.stage_focus,
        "weeks_in_stage":    profile.weeks_in_stage,
    }


@router.get("/habits")
async def get_habits(
    user_id: str          = Depends(_user_id),
    db:      AsyncSession = Depends(get_db),
) -> dict:
    """Return the stored lifestyle habits profile."""
    result = await db.execute(
        select(UserHabits).where(UserHabits.user_id == parse_uuid(user_id))
    )
    row: Optional[UserHabits] = result.scalar_one_or_none()
    if row is None:
        return {"user_id": user_id, "habits": None}

    return {
        "user_id": user_id,
        "habits": {
            "movement_enjoyed":   row.movement_enjoyed,
            "exercise_frequency": row.exercise_frequency,
            "alcohol":            row.alcohol,
            "caffeine":           row.caffeine,
            "smoking":            row.smoking,
            "sleep_schedule":     row.sleep_schedule,
            "typical_day":        row.typical_day,
            "stress_drivers":     row.stress_drivers,
            "decompress_via":     row.decompress_via,
        },
    }


@router.put("/habits")
async def update_habits(
    body:    HabitsUpdate,
    user_id: str          = Depends(_user_id),
    db:      AsyncSession = Depends(get_db),
) -> dict:
    """Replace or initialise the habits profile. Creates the user row if missing."""
    uid = parse_uuid(user_id)
    if uid is None:
        update_data = body.model_dump(exclude_none=True)
        return {"user_id": user_id, "updated_fields": list(update_data.keys())}

    # Upsert the User row (required before any FK-constrained child rows)
    user_result = await db.execute(select(User).where(User.id == uid))
    user_row: Optional[User] = user_result.scalar_one_or_none()
    if user_row is None:
        user_row = User(id=uid, name=body.name or "User")
        if body.goal:
            user_row.onboarding = {"goal": body.goal}
        db.add(user_row)
    else:
        if body.name:
            user_row.name = body.name
        if body.goal and user_row.onboarding is None:
            user_row.onboarding = {"goal": body.goal}
    await db.flush()  # persist user before habits FK check

    result = await db.execute(select(UserHabits).where(UserHabits.user_id == uid))
    row: Optional[UserHabits] = result.scalar_one_or_none()

    if row is None:
        row = UserHabits(user_id=uid)
        db.add(row)

    update_data = body.model_dump(exclude_none=True)
    for field, value in update_data.items():
        setattr(row, field, value)

    await db.commit()
    return {"user_id": user_id, "updated_fields": list(update_data.keys())}
