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


# ── Helpers ────────────────────────────────────────────────────────────────────

def _empty_fp():
    from model.baseline_builder import PersonalFingerprint
    return PersonalFingerprint()
