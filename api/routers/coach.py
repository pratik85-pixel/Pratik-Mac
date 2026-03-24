"""
api/routers/coach.py

Coaching message and conversation endpoints.

GET  /coach/post-session            — post-session message (requires session_id query param)
GET  /coach/nudge                   — short mid-day motivational nudge
POST /coach/conversation            — send a user message, receive coach reply
GET  /coach/conversation/history    — retrieve stored conversation events
DELETE /coach/conversation/{id}     — close an open conversation
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from outcomes.session_outcomes import SessionOutcome
from api.db.database import get_db
from api.db.schema import CoachMessage, ConversationEvent
from api.services.model_service import ModelService
from api.services.coach_service import CoachService
from api.services.conversation_service import ConversationService
from api.utils import parse_uuid

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/coach", tags=["coach"])

# ── Dependencies ───────────────────────────────────────────────────────────────

async def _user_id(x_user_id: Annotated[str, Header()]) -> str:
    if not x_user_id:
        raise HTTPException(status_code=401, detail="X-User-Id header required")
    return x_user_id

async def _model_svc(db: AsyncSession = Depends(get_db)) -> ModelService:
    return ModelService(db=db)

def _coach_svc(request: Request) -> CoachService:
    return request.app.state.coach_service

def _conv_svc(request: Request) -> ConversationService:
    return request.app.state.conversation_service


# ── Request / response models ──────────────────────────────────────────────────

class ConversationTurnRequest(BaseModel):
    message:         str
    conversation_id: Optional[str] = None  # None → opens a new conversation


class CoachReply(BaseModel):
    conversation_id: str
    turn_index:      int
    session_open:    bool
    safety_fired:    bool
    reply:           Optional[str]
    follow_up:       Optional[str]
    handoff_message: str


class MorningBriefResponse(BaseModel):
    day_state:      Optional[str]   # "green"|"yellow"|"red"
    day_confidence: Optional[str]   # "high"|"medium"|"low"
    brief_text:     Optional[str]
    evidence:       Optional[str]
    one_action:     Optional[str]
    generated_for:  Optional[str]   # YYYY-MM-DD
    is_stale:       bool            # True if generated_for < today IST
    plan:           list[dict]      # suggested plan items from UUP
    avoid_items:    list[dict]      # avoid items from UUP


class NudgeCheckResponse(BaseModel):
    should_nudge: bool
    message:      Optional[str]     # populated only when should_nudge=True
    reason:       str               # "ok"|"outside_window"|"cap_reached"|"no_data"


class EveningCheckinResponse(BaseModel):
    day_summary:      str
    tonight_priority: str
    trend_note:       str


class NightClosureResponse(BaseModel):
    updated_narrative: str
    tomorrow_seed:     str


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/post-session")
async def post_session_brief(
    request:    Request,
    user_id:    str          = Depends(_user_id),
    session_id: str          = Query(..., description="Completed session row ID"),
    model_svc:  ModelService = Depends(_model_svc),
    coach_svc:  CoachService = Depends(_coach_svc),
) -> dict:
    """
    Generate coaching message for a just-completed session.
    The session outcome must already be stored via POST /session/{id}/end.
    """
    # Retrieve cached outcome from session_service (held after end_session)
    svc = request.app.state.session_service
    outcome: Optional[SessionOutcome] = svc.get_cached_outcome(session_id)
    if outcome is None:
        raise HTTPException(status_code=404, detail="session outcome not found")

    fp      = await model_svc.get_fingerprint(user_id) or _empty_fp()
    profile = await model_svc.get_profile(user_id)
    user    = await model_svc.get_user(user_id)

    output = coach_svc.post_session(
        fp, profile, outcome,
        user_name=user.name if user else "there",
    )

    return {"trigger": "post_session", "session_id": session_id, **output}


@router.get("/nudge")
async def nudge(
    user_id:   str          = Depends(_user_id),
    model_svc: ModelService = Depends(_model_svc),
    coach_svc: CoachService = Depends(_coach_svc),
) -> dict:
    """Generate a short mid-day motivational nudge."""
    fp      = await model_svc.get_fingerprint(user_id) or _empty_fp()
    profile = await model_svc.get_profile(user_id)

    output = coach_svc.nudge(fp, profile)
    return {"trigger": "nudge", "user_id": user_id, **output}


@router.post("/conversation", response_model=CoachReply)
async def conversation_turn(
    body:      ConversationTurnRequest,
    user_id:   str                  = Depends(_user_id),
    conv_svc:  ConversationService  = Depends(_conv_svc),
    model_svc: ModelService         = Depends(_model_svc),
    db:        AsyncSession         = Depends(get_db),
) -> CoachReply:
    """
    Send a user message and receive the coach's reply.
    Opens a new conversation if no conversation_id is provided.
    """
    conversation_id = body.conversation_id
    if conversation_id is None:
        conversation_id = await conv_svc.open(user_id, trigger_context="user_initiated")

    try:
        result = await conv_svc.process_turn(
            conversation_id, body.message,
            model_service=model_svc, db=db,
        )
    except ValueError as exc:
        if "not found" in str(exc):
            # Stale conversation_id (server restarted, in-memory store wiped).
            # Open a fresh conversation and retry transparently.
            conversation_id = await conv_svc.open(user_id, trigger_context="user_initiated")
            result = await conv_svc.process_turn(
                conversation_id, body.message,
                model_service=model_svc, db=db,
            )
        else:
            raise

    if not result.session_open:
        await conv_svc.close_and_persist(conversation_id, db=db)

    payload = result.reply_payload or {}
    return CoachReply(
        conversation_id = result.conversation_id or conversation_id,
        turn_index      = result.turn_index,
        session_open    = result.session_open,
        safety_fired    = result.safety_fired,
        reply           = payload.get("reply"),
        follow_up       = payload.get("follow_up_question"),
        handoff_message = result.handoff_message,
    )


@router.get("/conversation/history")
async def conversation_history(
    user_id: str          = Depends(_user_id),
    limit:   int          = Query(default=50, le=200),
    db:      AsyncSession = Depends(get_db),
) -> dict:
    """Return recent conversation events for this user."""
    uid = parse_uuid(user_id)
    if uid is None:
        return {"user_id": user_id, "turns": []}
    result = await db.execute(
        select(ConversationEvent)
        .where(ConversationEvent.user_id == uid)
        .order_by(desc(ConversationEvent.ts))
        .limit(limit)
    )
    events = result.scalars().all()
    return {
        "user_id": user_id,
        "turns": [
            {
                "role":     e.role,
                "content":  e.content,
                "ts":       e.ts.isoformat() if e.ts else None,
                "plan_adjusted": e.plan_adjusted,
            }
            for e in reversed(list(events))
        ],
    }


@router.delete("/conversation/{conversation_id}")
async def close_conversation(
    conversation_id: str,
    user_id:  str                 = Depends(_user_id),
    conv_svc: ConversationService = Depends(_conv_svc),
    db:       AsyncSession        = Depends(get_db),
) -> dict:
    """Explicitly close a conversation session."""
    await conv_svc.close_and_persist(conversation_id, db=db)
    return {"closed": True, "conversation_id": conversation_id}


@router.get("/morning-brief", response_model=MorningBriefResponse)
async def get_morning_brief(
    user_id: str          = Depends(_user_id),
    db:      AsyncSession = Depends(get_db),
) -> MorningBriefResponse:
    """
    Return the cached morning brief for today.

    The brief is generated at first wakeup (sleep→background transition)
    and cached in UserUnifiedProfile. If no brief exists yet for today,
    returns is_stale=True with whatever the last stored values are.
    """
    from zoneinfo import ZoneInfo
    import api.db.schema as _db

    uid = parse_uuid(user_id)
    if uid is None:
        raise HTTPException(status_code=401, detail="Invalid X-User-Id")

    result = await db.execute(
        select(_db.UserUnifiedProfile).where(_db.UserUnifiedProfile.user_id == uid)
    )
    uup = result.scalar_one_or_none()

    IST = ZoneInfo("Asia/Kolkata")
    from datetime import date as _date
    today_ist = datetime.now(IST).date()

    generated_for = uup.morning_brief_generated_for if uup else None
    is_stale = (generated_for is None or generated_for < today_ist)

    plan = uup.suggested_plan_json or [] if uup else []
    avoid = uup.avoid_items_json or [] if uup else []

    return MorningBriefResponse(
        day_state      = uup.morning_brief_day_state if uup else None,
        day_confidence = uup.morning_brief_day_confidence if uup else None,
        brief_text     = uup.morning_brief_text if uup else None,
        evidence       = uup.morning_brief_evidence if uup else None,
        one_action     = uup.morning_brief_one_action if uup else None,
        generated_for  = generated_for.isoformat() if generated_for else None,
        is_stale       = is_stale,
        plan           = plan,
        avoid_items    = avoid,
    )


# ── Phase 5 endpoints ────────────────────────────────────────────────────────

@router.get("/nudge-check", response_model=NudgeCheckResponse)
async def nudge_check(
    user_id:   str          = Depends(_user_id),
    model_svc: ModelService = Depends(_model_svc),
    coach_svc: CoachService = Depends(_coach_svc),
    db:        AsyncSession = Depends(get_db),
) -> NudgeCheckResponse:
    """
    Decision gate — should the app push a nudge notification right now?

    Guardrails evaluated in order:
      1. IST time window (10:00 – 20:00)
      2. Rolling 4-hour nudge cap (NUDGE_CAP_PER_4H messages max)
      3. Data availability (trajectory must be non-empty)

    Returns should_nudge=True + generated message only when all gates pass.
    """
    from zoneinfo import ZoneInfo
    from datetime import timedelta
    from sqlalchemy import func
    import api.db.schema as _db
    from coach.data_assembler import assemble_for_user
    from config import CONFIG

    uid = parse_uuid(user_id)
    if uid is None:
        raise HTTPException(status_code=401, detail="Invalid X-User-Id")

    IST = ZoneInfo("Asia/Kolkata")
    cfg = CONFIG.coach
    now_ist = datetime.now(IST)

    # Gate 1 — time window
    if not (cfg.NUDGE_WINDOW_START_HOUR_IST <= now_ist.hour < cfg.NUDGE_WINDOW_END_HOUR_IST):
        return NudgeCheckResponse(should_nudge=False, message=None, reason="outside_window")

    # Gate 2 — cap check
    window_start = datetime.now(IST).astimezone().__class__.now() - timedelta(hours=4)
    # Use UTC-aware cutoff for DB comparison
    from datetime import timezone as _tz
    cutoff_utc = datetime.now(_tz.utc) - timedelta(hours=4)
    cap_result = await db.execute(
        select(func.count(_db.CoachMessage.id)).where(
            _db.CoachMessage.user_id    == uid,
            _db.CoachMessage.message_type == "nudge",
            _db.CoachMessage.created_at >= cutoff_utc,
        )
    )
    nudges_in_window = cap_result.scalar() or 0
    if nudges_in_window >= cfg.NUDGE_CAP_PER_4H:
        return NudgeCheckResponse(should_nudge=False, message=None, reason="cap_reached")

    # Gate 3 — data availability
    assembled = await assemble_for_user(db, uid)
    if not assembled.daily_trajectory:
        return NudgeCheckResponse(should_nudge=False, message=None, reason="no_data")

    # All gates passed — generate a nudge
    fp      = await model_svc.get_fingerprint(user_id) or _empty_fp()
    profile = await model_svc.get_profile(user_id)
    latest  = assembled.daily_trajectory[-1]
    output  = coach_svc.nudge(
        fp, profile,
        stress_score   = latest.get("stress_load"),
        recovery_score = latest.get("waking_recovery"),
    )
    message = output.get("summary") or output.get("action")
    return NudgeCheckResponse(should_nudge=True, message=message, reason="ok")


@router.get("/evening-checkin", response_model=EveningCheckinResponse)
async def evening_checkin(
    user_id:   str          = Depends(_user_id),
    coach_svc: CoachService = Depends(_coach_svc),
    db:        AsyncSession = Depends(get_db),
) -> EveningCheckinResponse:
    """
    Synthesise today's physio data into a brief evening check-in.
    Called at ~18:30 IST or on user demand.
    """
    from coach.data_assembler import assemble_for_user

    uid = parse_uuid(user_id)
    if uid is None:
        raise HTTPException(status_code=401, detail="Invalid X-User-Id")

    assembled = await assemble_for_user(db, uid)
    output    = coach_svc.evening_checkin(assembled)
    return EveningCheckinResponse(
        day_summary      = output.get("day_summary",      ""),
        tonight_priority = output.get("tonight_priority", ""),
        trend_note       = output.get("trend_note",       ""),
    )


@router.get("/night-closure", response_model=NightClosureResponse)
async def night_closure(
    user_id:   str          = Depends(_user_id),
    coach_svc: CoachService = Depends(_coach_svc),
    db:        AsyncSession = Depends(get_db),
) -> NightClosureResponse:
    """
    Generate tomorrow-seed and updated narrative.
    Gate: must be called at or after 21:30 IST — returns 409 if too early.
    Persists tomorrow_seed into UserUnifiedProfile.coach_narrative.
    """
    from zoneinfo import ZoneInfo
    from sqlalchemy import select as _select
    import api.db.schema as _db
    from coach.data_assembler import assemble_for_user
    from config import CONFIG

    uid = parse_uuid(user_id)
    if uid is None:
        raise HTTPException(status_code=401, detail="Invalid X-User-Id")

    IST = ZoneInfo("Asia/Kolkata")
    cfg = CONFIG.coach
    now_ist = datetime.now(IST)
    if (now_ist.hour, now_ist.minute) < (cfg.NIGHT_CLOSURE_HOUR_IST, cfg.NIGHT_CLOSURE_MINUTE_IST):
        raise HTTPException(status_code=409, detail="too_early")

    assembled = await assemble_for_user(db, uid)
    output    = coach_svc.night_closure(assembled)

    tomorrow_seed     = output.get("tomorrow_seed", "")
    updated_narrative = output.get("updated_narrative", "")

    # Persist tomorrow_seed into coach_narrative on UserUnifiedProfile
    uup_result = await db.execute(
        _select(_db.UserUnifiedProfile).where(_db.UserUnifiedProfile.user_id == uid)
    )
    uup = uup_result.scalar_one_or_none()
    if uup is not None:
        uup.coach_narrative = tomorrow_seed
        await db.commit()

    return NightClosureResponse(
        updated_narrative = updated_narrative,
        tomorrow_seed     = tomorrow_seed,
    )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _empty_fp():
    from model.baseline_builder import PersonalFingerprint
    return PersonalFingerprint()
