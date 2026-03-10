"""
api/routers/session.py

Session lifecycle endpoints.

POST /session/start    — create a session, register with SessionService
POST /session/end      — end a session, compute outcome, persist via OutcomeService
GET  /session/{id}/live    — poll current live metrics
GET  /session/{id}/result  — retrieve stored outcome
"""

from __future__ import annotations

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, func as sqlfunc
from sqlalchemy.ext.asyncio import AsyncSession

from sessions.session_prescriber import (
    PRF_CONFIRMED, PRF_FOUND, PRF_UNKNOWN, prescribe_session,
)
from outcomes.session_outcomes import SessionOutcome
from api.db.database import get_db
from api.db.schema import Session as SessionRow, PersonalModel as PersonalModelRow
from api.services.session_service import SessionService, LiveMetrics
from api.services.model_service import ModelService
from api.services.outcome_service import OutcomeService
from api.utils import parse_uuid

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/session", tags=["session"])


# ── Dependencies ───────────────────────────────────────────────────────────────

async def _user_id(x_user_id: Annotated[str, Header()]) -> str:
    if not x_user_id:
        raise HTTPException(status_code=401, detail="X-User-Id header required")
    return x_user_id

def _session_svc(request: Request) -> SessionService:
    return request.app.state.session_service

async def _model_svc(db: AsyncSession = Depends(get_db)) -> ModelService:
    return ModelService(db=db)

async def _outcome_svc(
    db:         AsyncSession          = Depends(get_db),
    model_svc:  ModelService          = Depends(_model_svc),
) -> OutcomeService:
    return OutcomeService(model_service=model_svc, db=db)


# ── Request / response models ──────────────────────────────────────────────────

class StartSessionRequest(BaseModel):
    # The minimum info needed to prescribe a session
    prf_status:    str   = PRF_UNKNOWN      # PRF_UNKNOWN | PRF_FOUND | PRF_CONFIRMED
    stored_prf_bpm: Optional[float] = None
    session_type:  str   = "full"           # "full" | "rest" | "background"
    load_score:    Optional[float] = None   # 0.0–1.0, None → computed from model
    attention_anchor: Optional[str] = None  # "heart" | "belly" | etc.
    duration_minutes: Optional[int] = None

class StartSessionResponse(BaseModel):
    session_id:    str
    practice_type: str
    pacer:         Optional[dict]
    duration_minutes: int
    gates_required: bool
    prf_target_bpm: Optional[float]
    session_notes: list[str]
    tier:          int

class EndSessionRequest(BaseModel):
    morning_rmssd_ms:    Optional[float] = None
    personal_floor_rmssd: Optional[float] = None

class LiveMetricsResponse(BaseModel):
    session_id:     str
    elapsed_s:      float
    coherence:      Optional[float]
    zone:           Optional[int]
    rmssd_ms:       Optional[float]
    breath_bpm:     Optional[float]
    windows_so_far: int
    prf_bpm:        Optional[float]


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/start", response_model=StartSessionResponse)
async def start_session(
    body:      StartSessionRequest,
    user_id:   str              = Depends(_user_id),
    model_svc: ModelService     = Depends(_model_svc),
    svc:       SessionService   = Depends(_session_svc),
    db:        AsyncSession     = Depends(get_db),
) -> StartSessionResponse:
    """
    Prescribe and start a new guided session for the user.
    Returns the session_id (for WebSocket handshake) and the full session config.
    """
    profile = await model_svc.get_profile(user_id)
    stage   = profile.stage

    # Pull PRF status + total completed sessions from DB  ────────────────────
    uid = parse_uuid(user_id)
    prf_status_from_db = body.prf_status
    prf_bpm_from_db    = body.stored_prf_bpm
    total_sessions     = 0

    if uid is not None:
        pm_res = await db.execute(
            select(PersonalModelRow).where(PersonalModelRow.user_id == uid)
        )
        pm_row = pm_res.scalar_one_or_none()
        if pm_row is not None:
            # Use DB-stored PRF only if client didn't supply one
            if pm_row.prf_status and body.prf_status == PRF_UNKNOWN:
                prf_status_from_db = pm_row.prf_status
            if pm_row.prf_bpm and body.stored_prf_bpm is None:
                prf_bpm_from_db = pm_row.prf_bpm

        count_res = await db.execute(
            select(sqlfunc.count(SessionRow.id)).where(
                SessionRow.user_id == uid,
                SessionRow.context == "session",
            )
        )
        total_sessions = count_res.scalar_one() or 0

    practice = prescribe_session(
        stage               = stage,
        prf_status          = prf_status_from_db,
        stored_prf_bpm      = prf_bpm_from_db,
        session_type        = body.session_type,
        load_score          = body.load_score if body.load_score is not None else 0.0,
        attention_anchor    = body.attention_anchor,
        total_sessions_completed = total_sessions,
        duration_minutes    = body.duration_minutes,
    )

    session_id = svc.start_session(user_id, practice)

    return StartSessionResponse(
        session_id       = session_id,
        practice_type    = practice.practice_type,
        pacer            = practice.to_dict().get("pacer"),
        duration_minutes = practice.duration_minutes,
        gates_required   = practice.gates_required,
        prf_target_bpm   = practice.prf_target_bpm,
        session_notes    = practice.session_notes,
        tier             = practice.tier,
    )


@router.post("/{session_id}/end")
async def end_session(
    session_id:   str,
    body:         EndSessionRequest,
    user_id:      str             = Depends(_user_id),
    svc:          SessionService  = Depends(_session_svc),
    outcome_svc:  OutcomeService  = Depends(_outcome_svc),
) -> dict:
    """
    End the session, compute SessionOutcome, persist to DB, return summary.
    """
    outcome: Optional[SessionOutcome] = svc.end_session(
        session_id,
        morning_rmssd_ms     = body.morning_rmssd_ms,
        personal_floor_rmssd = body.personal_floor_rmssd,
    )

    if outcome is None:
        raise HTTPException(status_code=404, detail="session not found or no data recorded")

    row_id = await outcome_svc.persist_session_outcome(user_id, outcome)

    return {
        "session_id":    row_id,
        "practice_type": outcome.practice_type,
        "score":         round(outcome.session_score * 100, 1),
        "coherence_avg": round(outcome.coherence_avg, 3) if outcome.coherence_avg else None,
        "zone_time": {
            "z1_s": outcome.zone_1_seconds,
            "z2_s": outcome.zone_2_seconds,
            "z3_s": outcome.zone_3_seconds,
            "z4_s": outcome.zone_4_seconds,
        },
        "rmssd_pre_ms":   outcome.rmssd_pre_ms,
        "rmssd_post_ms":  outcome.rmssd_post_ms,
        "arc_completed":  outcome.arc_completed,
        "data_quality":   round(outcome.data_quality, 3),
        "notes":          outcome.notes,
    }


@router.get("/{session_id}/live", response_model=LiveMetricsResponse)
async def get_live_metrics(
    session_id: str,
    user_id:    str           = Depends(_user_id),
    svc:        SessionService = Depends(_session_svc),
) -> LiveMetricsResponse:
    """Poll current live metrics for an active session (WebSocket alternative)."""
    metrics: Optional[LiveMetrics] = svc.get_live_metrics(session_id)
    if metrics is None:
        raise HTTPException(status_code=404, detail="session not found or no data yet")
    return LiveMetricsResponse(**metrics.__dict__)
