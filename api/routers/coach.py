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
import asyncio
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from outcomes.session_outcomes import SessionOutcome
from api.db.database import get_db, AsyncSessionLocal
from api.db.schema import CoachMessage, ConversationEvent
from api.services.model_service import ModelService
from api.services.coach_service import CoachService
from api.services.conversation_service import (
    ConversationService,
    ConversationNotFoundError,
    ConversationOwnerMismatchError,
)
from api.services.tracking_service import TrackingService
from api.utils import parse_uuid
from tracking.cycle_boundaries import local_today, product_calendar_timezone
from api.rate_limiter import conversation_limiter, llm_unit_limiter
from api.auth import UserIdDep

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/coach", tags=["coach"])


def _user_uuid_for_coach(user_id: str) -> uuid.UUID:
    """
    Map X-User-Id to a UUID for DB queries.
    Valid UUID strings pass through; arbitrary strings (e.g. tests) get a stable UUID5.
    """
    u = parse_uuid(user_id)
    if u is not None:
        return u
    return uuid.uuid5(uuid.NAMESPACE_URL, f"zenflow:user:{user_id.strip()}")


# ── Dependencies ───────────────────────────────────────────────────────────────

async def _model_svc(db: AsyncSession = Depends(get_db)) -> ModelService:
    return ModelService(db=db)

def _coach_svc(request: Request) -> CoachService:
    return request.app.state.coach_service

def _conv_svc(request: Request) -> ConversationService:
    return request.app.state.conversation_service


async def _tracking_svc_coach(
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

class ConversationTurnRequest(BaseModel):
    message:         str = Field(..., max_length=2_000)
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
    # Legacy / test-friendly aliases (same content as brief_text / one_action)
    summary:        Optional[str] = None
    action:         Optional[str] = None
    message:        Optional[str] = None
    generated_for:  Optional[str]   # YYYY-MM-DD
    is_stale:       bool            # True if generated_for < today IST
    plan:           list[dict]      # suggested plan items from UUP
    avoid_items:    list[dict]      # avoid items from UUP
    # ── Band-wear coverage (deterministic, echoed from packet) ─────────────
    # These are read-only UI cues — independent of the LLM output.
    yesterday_wear_hours:       Optional[float] = None
    yesterday_coverage_label:   Optional[str] = None   # "full"|"partial"|"low"|"none"
    has_sleep_data_yesterday:   Optional[bool] = None


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


class YesterdaySummaryResponse(BaseModel):
    weekly_trend:              Optional[str] = None
    yesterday_stress:          Optional[str] = None
    yesterday_waking_recovery: Optional[str] = None
    yesterday_sleep_recovery:  Optional[str] = None
    yesterday_adherence:       Optional[str] = None
    generated_for:             Optional[str] = None  # YYYY-MM-DD
    is_stale:                  bool

# ── Endpoints ──────────────────────────────────────────────────────────────────

async def _gated_nudge_decision(
    *,
    user_id: str,
    db: AsyncSession,
    model_svc: ModelService,
    coach_svc: CoachService,
) -> NudgeCheckResponse:
    from datetime import timedelta, timezone as _tz
    from sqlalchemy import func
    import api.db.schema as _db
    from coach.data_assembler import assemble_for_user
    from config import CONFIG

    uid = _user_uuid_for_coach(user_id)

    cfg = CONFIG.coach
    now_local = datetime.now(product_calendar_timezone())

    # Gate 1 — time window
    if not (cfg.NUDGE_WINDOW_START_HOUR_IST <= now_local.hour < cfg.NUDGE_WINDOW_END_HOUR_IST):
        return NudgeCheckResponse(should_nudge=False, message=None, reason="outside_window")

    # Gate 2 — cap check (rolling 4h window, UTC-aware for DB timestamps)
    cutoff_utc = datetime.now(_tz.utc) - timedelta(hours=4)
    cap_result = await db.execute(
        select(func.count(_db.CoachMessage.id)).where(
            _db.CoachMessage.user_id == uid,
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

    # All gates passed — generate nudge
    fp = await model_svc.get_fingerprint(user_id) or _empty_fp()
    profile = await model_svc.get_profile(user_id)
    latest = assembled.daily_trajectory[-1]
    output = await asyncio.to_thread(
        coach_svc.nudge,
        fp,
        profile,
        stress_score=latest.get("stress_load"),
        recovery_score=latest.get("waking_recovery"),
    )
    message = output.get("summary") or output.get("action")
    if message:
        db.add(
            CoachMessage(
                user_id=uid,
                message_type="nudge",
                summary=message[:8000],
                reason="nudge_check_gate_passed",
            )
        )
        await db.commit()
    return NudgeCheckResponse(should_nudge=True, message=message, reason="ok")

@router.get("/post-session")
async def post_session_brief(
    request:    Request,
    user_id:    UserIdDep,
    session_id: str          = Query(..., description="Completed session row ID"),
    model_svc:  ModelService = Depends(_model_svc),
    coach_svc:  CoachService = Depends(_coach_svc),
) -> dict:
    """
    Generate coaching message for a just-completed session.
    The session outcome must already be stored via POST /session/{id}/end.
    """
    llm_unit_limiter.check(user_id)
    # Retrieve cached outcome from session_service (held after end_session)
    svc = request.app.state.session_service
    outcome: Optional[SessionOutcome] = svc.get_cached_outcome(session_id, user_id=user_id)
    if outcome is None:
        raise HTTPException(status_code=404, detail="session outcome not found")

    fp      = await model_svc.get_fingerprint(user_id) or _empty_fp()
    profile = await model_svc.get_profile(user_id)
    user    = await model_svc.get_user(user_id)

    output = await asyncio.to_thread(
        coach_svc.post_session,
        fp,
        profile,
        outcome,
        user_name=user.name if user else "there",
    )

    return {"trigger": "post_session", "session_id": session_id, **output}


@router.get("/nudge")
async def nudge(
    user_id:   UserIdDep,
    model_svc: ModelService = Depends(_model_svc),
    coach_svc: CoachService = Depends(_coach_svc),
    db:        AsyncSession = Depends(get_db),
) -> dict:
    """Generate a short mid-day nudge when gates (window/cap/data) pass."""
    llm_unit_limiter.check(user_id)
    decision = await _gated_nudge_decision(
        user_id=user_id,
        db=db,
        model_svc=model_svc,
        coach_svc=coach_svc,
    )
    return {
        "trigger": "nudge",
        "user_id": user_id,
        "should_nudge": decision.should_nudge,
        "reason": decision.reason,
        "message": decision.message,
        "summary": decision.message,
    }


@router.post("/conversation", response_model=CoachReply)
async def conversation_turn(
    body:      ConversationTurnRequest,
    user_id:   UserIdDep,
    conv_svc:  ConversationService  = Depends(_conv_svc),
    model_svc: ModelService         = Depends(_model_svc),
    db:        AsyncSession         = Depends(get_db),
) -> CoachReply:
    """
    Send a user message and receive the coach's reply.
    Opens a new conversation if no conversation_id is provided.
    """
    conversation_limiter.check(user_id)
    conversation_id = body.conversation_id
    if conversation_id is None:
        conversation_id = await conv_svc.open(user_id, trigger_context="user_initiated")

    try:
        result = await conv_svc.process_turn(
            conversation_id, body.message,
            model_service=model_svc, db=db,
            caller_user_id=user_id,
        )
    except ConversationNotFoundError:
        # Stale conversation_id (server restarted, in-memory store wiped).
        # Open a fresh conversation and retry transparently.
        conversation_id = await conv_svc.open(user_id, trigger_context="user_initiated")
        result = await conv_svc.process_turn(
            conversation_id, body.message,
            model_service=model_svc, db=db,
            caller_user_id=user_id,
        )
    except ConversationOwnerMismatchError:
        raise HTTPException(status_code=403, detail="conversation does not belong to caller")

    if not result.session_open:
        try:
            await conv_svc.close_and_persist(
                conversation_id, db=db, caller_user_id=user_id,
            )
        except ConversationOwnerMismatchError:
            # Race: owner changed between process_turn and close — safe to ignore.
            logger.warning("owner_mismatch on close_and_persist conv=%s", conversation_id)

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
    user_id: UserIdDep,
    limit:   int          = Query(default=50, le=200),
    db:      AsyncSession = Depends(get_db),
) -> dict:
    """Return recent conversation events for this user."""
    uid = _user_uuid_for_coach(user_id)
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
    user_id:  UserIdDep,
    conv_svc: ConversationService = Depends(_conv_svc),
    db:       AsyncSession        = Depends(get_db),
) -> dict:
    """Explicitly close a conversation session (owner-only)."""
    try:
        await conv_svc.close_and_persist(
            conversation_id, db=db, caller_user_id=user_id,
        )
    except ConversationOwnerMismatchError:
        raise HTTPException(status_code=403, detail="conversation does not belong to caller")
    return {"closed": True, "conversation_id": conversation_id}


@router.get("/morning-brief", response_model=MorningBriefResponse)
async def get_morning_brief(
    request: Request,
    user_id: UserIdDep,
    db:      AsyncSession = Depends(get_db),
    track_svc: TrackingService = Depends(_tracking_svc_coach),
) -> MorningBriefResponse:
    """
    Return the cached morning brief for today.

    The brief is typically generated during morning reset and cached in
    UserUnifiedProfile. If the cache is stale/missing for today, this endpoint
    attempts a best-effort refresh before returning.
    """
    llm_unit_limiter.check(user_id)
    import api.db.schema as _db
    from datetime import UTC as _UTC, datetime as _dt
    from coach.morning_brief import clear_morning_bundle_uup, generate_morning_brief
    from coach.input_builder import _compute_band_coverage

    uid = _user_uuid_for_coach(user_id)

    today_ist = local_today()

    # Deterministic band-wear coverage for the response payload (independent
    # of anything the LLM writes). Never raises into the endpoint.
    coverage: dict = {}
    try:
        coverage = await _compute_band_coverage(db, uid, now_utc=_dt.now(_UTC))
    except Exception:
        logger.exception("morning-brief: band coverage compute failed user=%s", user_id)
        coverage = {}

    recap = await track_svc.get_morning_recap()
    if not recap.get("summary"):
        await clear_morning_bundle_uup(db, uid, today_ist)
        return MorningBriefResponse(
            day_state=None,
            day_confidence=None,
            brief_text=None,
            evidence=None,
            one_action=None,
            summary=None,
            action=None,
            message=None,
            generated_for=today_ist.isoformat(),
            is_stale=False,
            plan=[],
            avoid_items=[],
            yesterday_wear_hours=coverage.get("yesterday_wear_hours"),
            yesterday_coverage_label=coverage.get("yesterday_coverage_label"),
            has_sleep_data_yesterday=coverage.get("has_sleep_data_yesterday"),
        )

    result = await db.execute(
        select(_db.UserUnifiedProfile).where(_db.UserUnifiedProfile.user_id == uid)
    )
    uup = result.scalar_one_or_none()

    generated_for = uup.morning_brief_generated_for if uup else None
    # Staleness uses IST calendar day so a new day always re-evaluates even if
    # morning-reset cycle date is stuck (band overnight tagging missed).
    is_stale = (generated_for is None or generated_for < today_ist)
    brief_empty_for_today = bool(
        uup
        and generated_for == today_ist
        and not any(
            [
                uup.morning_brief_day_state,
                uup.morning_brief_day_confidence,
                uup.morning_brief_text,
                uup.morning_brief_evidence,
                uup.morning_brief_one_action,
            ]
        )
    )

    # Fire-and-forget morning bundle when recap exists but brief fields are empty
    # and we are not about to run synchronous generate in this same request
    # (avoids duplicate LLM work when is_stale/brief_empty_for_today is true).
    will_sync_generate = is_stale or brief_empty_for_today
    brief_missing = not uup or not any(
        [
            uup.morning_brief_day_state,
            uup.morning_brief_day_confidence,
            uup.morning_brief_text,
            uup.morning_brief_evidence,
            uup.morning_brief_one_action,
        ]
    )
    if recap.get("summary") and brief_missing and not will_sync_generate:
        from api.services.morning_bundle_orchestrator import MorningBundleOrchestrator

        MorningBundleOrchestrator(
            AsyncSessionLocal,
            getattr(request.app.state, "llm_client", None),
        ).schedule(str(user_id))

    if is_stale or brief_empty_for_today:
        # Lazy refresh path: backfill this cycle's brief when ingest-time trigger
        # was missed (e.g., no qualifying reset event yet).
        llm_client = getattr(request.app.state, "llm_client", None)
        await generate_morning_brief(AsyncSessionLocal, uid, llm_client)

        result = await db.execute(
            select(_db.UserUnifiedProfile).where(_db.UserUnifiedProfile.user_id == uid)
        )
        uup = result.scalar_one_or_none()
        generated_for = uup.morning_brief_generated_for if uup else None
        is_stale = (generated_for is None or generated_for < today_ist)

    plan = uup.suggested_plan_json or [] if uup else []
    avoid = uup.avoid_items_json or [] if uup else []

    bt = uup.morning_brief_text if uup else None
    oa = uup.morning_brief_one_action if uup else None
    return MorningBriefResponse(
        day_state      = uup.morning_brief_day_state if uup else None,
        day_confidence = uup.morning_brief_day_confidence if uup else None,
        brief_text     = bt,
        evidence       = uup.morning_brief_evidence if uup else None,
        one_action     = oa,
        summary        = bt,
        action         = oa,
        message        = bt,
        generated_for  = generated_for.isoformat() if generated_for else None,
        is_stale       = is_stale,
        plan           = plan,
        avoid_items    = avoid,
        yesterday_wear_hours     = coverage.get("yesterday_wear_hours"),
        yesterday_coverage_label = coverage.get("yesterday_coverage_label"),
        has_sleep_data_yesterday = coverage.get("has_sleep_data_yesterday"),
    )


@router.get("/yesterday-summary", response_model=YesterdaySummaryResponse)
async def get_yesterday_summary(
    request: Request,
    user_id: UserIdDep,
    db:      AsyncSession = Depends(get_db),
    track_svc: TrackingService = Depends(_tracking_svc_coach),
) -> YesterdaySummaryResponse:
    """
    Return cached \"Yesterday summary\" for the current IST cycle.

    Generated best-effort and cached in UserUnifiedProfile.
    """
    llm_unit_limiter.check(user_id)
    import api.db.schema as _db
    from coach.yesterday_summary import clear_yesterday_summary_uup, generate_yesterday_summary

    uid = _user_uuid_for_coach(user_id)
    today_ist = local_today()

    recap = await track_svc.get_morning_recap()
    if not recap.get("summary"):
        await clear_yesterday_summary_uup(db, uid, today_ist)
        return YesterdaySummaryResponse(
            weekly_trend=None,
            yesterday_stress=None,
            yesterday_waking_recovery=None,
            yesterday_sleep_recovery=None,
            yesterday_adherence=None,
            generated_for=today_ist.isoformat(),
            is_stale=False,
        )

    result = await db.execute(
        select(_db.UserUnifiedProfile).where(_db.UserUnifiedProfile.user_id == uid)
    )
    uup = result.scalar_one_or_none()

    generated_for = uup.yesterday_summary_generated_for if uup else None
    is_stale = (generated_for is None or generated_for < today_ist)
    empty_for_today = bool(
        uup
        and generated_for == today_ist
        and not any(
            [
                uup.yesterday_summary_weekly_trend,
                uup.yesterday_summary_stress,
                uup.yesterday_summary_waking_recovery,
                uup.yesterday_summary_sleep_recovery,
                uup.yesterday_summary_adherence,
            ]
        )
    )

    if is_stale or empty_for_today:
        llm_client = getattr(request.app.state, "llm_client", None)
        await generate_yesterday_summary(AsyncSessionLocal, uid, llm_client)
        result = await db.execute(
            select(_db.UserUnifiedProfile).where(_db.UserUnifiedProfile.user_id == uid)
        )
        uup = result.scalar_one_or_none()
        generated_for = uup.yesterday_summary_generated_for if uup else None
        is_stale = (generated_for is None or generated_for < today_ist)

    waking = uup.yesterday_summary_waking_recovery if uup else None
    sleep = uup.yesterday_summary_sleep_recovery if uup else None

    return YesterdaySummaryResponse(
        weekly_trend=uup.yesterday_summary_weekly_trend if uup else None,
        yesterday_stress=uup.yesterday_summary_stress if uup else None,
        yesterday_waking_recovery=waking,
        yesterday_sleep_recovery=sleep,
        yesterday_adherence=uup.yesterday_summary_adherence if uup else None,
        generated_for=generated_for.isoformat() if generated_for else None,
        is_stale=is_stale,
    )

# ── Phase 5 endpoints ────────────────────────────────────────────────────────

@router.get("/nudge-check", response_model=NudgeCheckResponse)
async def nudge_check(
    user_id:   UserIdDep,
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
    llm_unit_limiter.check(user_id)
    return await _gated_nudge_decision(
        user_id=user_id,
        db=db,
        model_svc=model_svc,
        coach_svc=coach_svc,
    )


@router.get("/evening-checkin", response_model=EveningCheckinResponse)
async def evening_checkin(
    user_id:   UserIdDep,
    coach_svc: CoachService = Depends(_coach_svc),
    db:        AsyncSession = Depends(get_db),
) -> EveningCheckinResponse:
    """
    Synthesise today's physio data into a brief evening check-in.
    Called at ~18:30 IST or on user demand.
    """
    llm_unit_limiter.check(user_id)
    from coach.data_assembler import assemble_for_user

    uid = _user_uuid_for_coach(user_id)

    assembled = await assemble_for_user(db, uid)
    output = await asyncio.to_thread(coach_svc.evening_checkin, assembled)
    return EveningCheckinResponse(
        day_summary      = output.get("day_summary",      ""),
        tonight_priority = output.get("tonight_priority", ""),
        trend_note       = output.get("trend_note",       ""),
    )


@router.get("/night-closure", response_model=NightClosureResponse)
async def night_closure(
    user_id:   UserIdDep,
    coach_svc: CoachService = Depends(_coach_svc),
    db:        AsyncSession = Depends(get_db),
) -> NightClosureResponse:
    """
    Generate tomorrow-seed and updated narrative.
    Gate: must be called at or after 21:30 IST — returns 409 if too early.
    Persists tomorrow_seed into UserUnifiedProfile.coach_narrative.
    """
    llm_unit_limiter.check(user_id)
    from sqlalchemy import select as _select
    import api.db.schema as _db
    from coach.data_assembler import assemble_for_user
    from config import CONFIG

    uid = _user_uuid_for_coach(user_id)

    cfg = CONFIG.coach
    now_ist = datetime.now(product_calendar_timezone())
    if (now_ist.hour, now_ist.minute) < (cfg.NIGHT_CLOSURE_HOUR_IST, cfg.NIGHT_CLOSURE_MINUTE_IST):
        raise HTTPException(status_code=409, detail="too_early")

    assembled = await assemble_for_user(db, uid)
    output = await asyncio.to_thread(coach_svc.night_closure, assembled)

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
