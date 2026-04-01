"""
api/routers/psych.py

Psychological profile endpoints.

GET  /psych/profile            — fetch inferred psych profile
POST /psych/mood               — log mood/energy/anxiety scores
POST /psych/anxiety            — log anxiety trigger event
POST /psych/rebuild            — trigger full profile recompute
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import UserIdDep
from api.db.database import get_db
from api.utils import parse_uuid
from api.services.psych_service import (
    load_psych_profile,
    log_anxiety_event,
    log_mood,
    rebuild_profile,
)
from psych.psych_schema import ANXIETY_TRIGGER_TYPES

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/psych", tags=["psych"])


# ── Dependencies ───────────────────────────────────────────────────────────────

# ── Request / response models ──────────────────────────────────────────────────

class AnxiestTriggerOut(BaseModel):
    trigger_type: str
    count:        int
    avg_severity: float
    strength:     float


class ActivityImpactOut(BaseModel):
    slug:            str
    count:           int
    avg_score_delta: float


class PsychProfileResponse(BaseModel):
    social_energy_type:      str
    social_hrv_delta_avg:    float
    social_event_count:      int
    anxiety_sensitivity:     float
    top_anxiety_triggers:    list[AnxiestTriggerOut]
    top_calming_activities:  list[ActivityImpactOut]
    top_stress_activities:   list[ActivityImpactOut]
    primary_recovery_style:  str
    discipline_index:        float
    streak_current:          int
    streak_best:             int
    mood_baseline:           str
    mood_score_avg:          Optional[float]
    interoception_alignment: Optional[float]
    data_confidence:         float
    coach_insight:           Optional[str]


class MoodLogRequest(BaseModel):
    mood_score:             float = Field(..., ge=1.0, le=5.0, description="Overall mood 1–5")
    energy_score:           Optional[float] = Field(None, ge=1.0, le=5.0)
    anxiety_score:          Optional[float] = Field(None, ge=1.0, le=5.0)
    social_desire:          Optional[float] = Field(None, ge=1.0, le=5.0, description="1=want alone, 5=want people")
    readiness_score_at_log: Optional[float] = Field(None, ge=0.0, le=100.0)
    stress_score_at_log:    Optional[float] = Field(None, ge=0.0, le=100.0)
    recovery_score_at_log:  Optional[float] = Field(None, ge=0.0, le=100.0)
    source:                 str = "manual"
    notes:                  Optional[str] = None


class MoodLogResponse(BaseModel):
    id: str


class AnxietyEventRequest(BaseModel):
    trigger_type:          str = Field(..., description=f"One of: {', '.join(ANXIETY_TRIGGER_TYPES)}")
    severity:              str = Field(..., pattern=r"^(mild|moderate|severe)$")
    stress_score_at_event: float = Field(..., ge=0.0, le=100.0)
    recovery_score_drop:   Optional[float] = Field(None, ge=0.0, le=100.0)
    resolution_activity:   Optional[str] = None
    resolved:              bool = False
    reported_via:          str = "manual"


class AnxietyEventResponse(BaseModel):
    id: str


class RebuildResponse(BaseModel):
    data_confidence: float
    coach_insight:   Optional[str]
    message:         str


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/profile", response_model=PsychProfileResponse)
async def get_psych_profile(
    user_id: UserIdDep,
    db: AsyncSession = Depends(get_db),
) -> PsychProfileResponse:
    """
    Return the most recent computed PsychProfile.
    Returns 404 if no profile has been built yet.
    """
    uid = parse_uuid(user_id)
    if uid is None:
        raise HTTPException(status_code=401, detail="Invalid user id")

    profile = await load_psych_profile(db, uid)
    if profile is None:
        raise HTTPException(
            status_code=404,
            detail="No psych profile yet. POST /psych/rebuild to generate one.",
        )

    return PsychProfileResponse(
        social_energy_type      = profile.social_energy_type,
        social_hrv_delta_avg    = profile.social_hrv_delta_avg,
        social_event_count      = profile.social_event_count,
        anxiety_sensitivity     = profile.anxiety_sensitivity,
        top_anxiety_triggers    = [
            AnxiestTriggerOut(**t.__dict__) for t in profile.top_anxiety_triggers
        ],
        top_calming_activities  = [
            ActivityImpactOut(**a.__dict__) for a in profile.top_calming_activities
        ],
        top_stress_activities   = [
            ActivityImpactOut(**a.__dict__) for a in profile.top_stress_activities
        ],
        primary_recovery_style  = profile.primary_recovery_style,
        discipline_index        = profile.discipline_index,
        streak_current          = profile.streak_current,
        streak_best             = profile.streak_best,
        mood_baseline           = profile.mood_baseline,
        mood_score_avg          = profile.mood_score_avg,
        interoception_alignment = profile.interoception_alignment,
        data_confidence         = profile.data_confidence,
        coach_insight           = profile.coach_insight,
    )


@router.post("/mood", response_model=MoodLogResponse, status_code=201)
async def post_mood_log(
    body: MoodLogRequest,
    user_id: UserIdDep,
    db: AsyncSession = Depends(get_db),
) -> MoodLogResponse:
    """
    Log subjective mood/energy/anxiety state.
    Scores are 1–5; physiological context scores (readiness etc.) are 0–100.
    """
    uid = parse_uuid(user_id)
    if uid is None:
        raise HTTPException(status_code=401, detail="Invalid user id")

    row_id = await log_mood(
        db,
        uid,
        mood_score              = body.mood_score,
        energy_score            = body.energy_score,
        anxiety_score           = body.anxiety_score,
        social_desire           = body.social_desire,
        readiness_score_at_log  = body.readiness_score_at_log,
        stress_score_at_log     = body.stress_score_at_log,
        recovery_score_at_log   = body.recovery_score_at_log,
        source                  = body.source,
        notes                   = body.notes,
    )
    await db.commit()
    return MoodLogResponse(id=row_id)


@router.post("/anxiety", response_model=AnxietyEventResponse, status_code=201)
async def post_anxiety_event(
    body: AnxietyEventRequest,
    user_id: UserIdDep,
    db: AsyncSession = Depends(get_db),
) -> AnxietyEventResponse:
    """
    Log a structured anxiety trigger event.
    """
    uid = parse_uuid(user_id)
    if uid is None:
        raise HTTPException(status_code=401, detail="Invalid user id")

    if body.trigger_type not in ANXIETY_TRIGGER_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"trigger_type must be one of: {', '.join(ANXIETY_TRIGGER_TYPES)}",
        )

    row_id = await log_anxiety_event(
        db,
        uid,
        trigger_type          = body.trigger_type,
        severity              = body.severity,
        stress_score_at_event = body.stress_score_at_event,
        recovery_score_drop   = body.recovery_score_drop,
        resolution_activity   = body.resolution_activity,
        resolved              = body.resolved,
        reported_via          = body.reported_via,
    )
    await db.commit()
    return AnxietyEventResponse(id=row_id)


@router.post("/rebuild", response_model=RebuildResponse)
async def post_rebuild_profile(
    user_id: UserIdDep,
    db: AsyncSession = Depends(get_db),
) -> RebuildResponse:
    """
    Recompute the full PsychProfile from all available data.
    This is an idempotent operation — safe to call multiple times.
    """
    uid = parse_uuid(user_id)
    if uid is None:
        raise HTTPException(status_code=401, detail="Invalid user id")

    profile = await rebuild_profile(db, uid)
    await db.commit()

    return RebuildResponse(
        data_confidence = profile.data_confidence,
        coach_insight   = profile.coach_insight,
        message         = (
            f"Profile rebuilt. Confidence: {profile.data_confidence:.0%}. "
            f"Dimensions: social={profile.social_energy_type}, "
            f"discipline={profile.discipline_index:.0f}/100, "
            f"mood={profile.mood_baseline}."
        ),
    )
