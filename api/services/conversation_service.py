"""
api/services/conversation_service.py

Manages coaching conversation state across turns.

Wraps `coach.conversation.ConversationManager` and provides the
context-building closure that the ConversationManager needs on each turn.

Design
------
- One `ConversationManager` per app instance (holds the MemoryStore).
- Sessions are keyed by `conversation_id` — a UUID generated on open.
- The model_service is injected so the service can pull the latest
  fingerprint and profile for each turn's context.
- All DB persistence of conversation events is done via the db session
  injected at call time, not stored on the service itself.
"""

from __future__ import annotations

import logging
import uuid
import asyncio
from time import perf_counter
from datetime import datetime, UTC
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from archetypes.scorer import NSHealthProfile
from coach.context_builder import build_coach_context, CoachContext
from coach.conversation import ConversationManager, TurnResult
from coach.conversation_extractor import extract_signals_from_message
from coach.data_assembler import assemble_for_user, AssembledContext
from coach.memory_store import MemoryStore
from coach.plan_replanner import DailyPrescription, HabitSignal, compute_daily_prescription
from coach.tone_selector import select_tone
from coach.coach_api import generate_response
from model.baseline_builder import PersonalFingerprint
from api.db.schema import ConversationEvent, HabitEvent
from api.services.model_service import ModelService
from api.services import profile_service as _profile_svc
from api.utils import parse_uuid

logger = logging.getLogger(__name__)

# Persist durable facts mid-conversation when extractor confidence is high enough.
_FACT_PERSIST_MIN_CONFIDENCE = 0.8
_COACH_TURN_TIMEOUT_S = 45.0

# Conversation extractor signal → HabitEvent.event_type mapping
# Any signal not in this map is stored directly under its label (truncated to 40 chars).
_SIGNAL_TO_EVENT_TYPE: dict[str, str] = {
    "alcohol_event":       "alcohol",
    "coffee_event":        "caffeine",
    "late_night_event":    "late_night",
    "stressful_event":     "stressful_event",
    "poor_sleep_event":    "poor_sleep",
    "exercise_event":      "exercise",
    "sports_activity":     "sports",
    "social_time":         "social_time",
    "nature_time_event":   "nature_time",
    "cold_shower_event":   "cold_shower",
    "entertainment_event": "entertainment",
}

logger = logging.getLogger(__name__)


class ConversationService:
    """
    Singleton service — one instance per app.
    Inject into `app.state.conversation_service` at startup.
    """

    def __init__(self, llm_client: Optional[Any] = None) -> None:
        self._llm        = llm_client
        self._store      = MemoryStore()
        self._scratch_profile: Optional[NSHealthProfile] = None
        self._manager    = ConversationManager(
            store=self._store,
            coach_api_fn=lambda ctx: generate_response(ctx, self._scratch_profile, self._llm),
        )

    # ── Session lifecycle ──────────────────────────────────────────────────────

    async def open(
        self,
        user_id:         str,
        trigger_context: str = "",
    ) -> str:
        """Open a conversation session and return the conversation_id."""
        state = self._manager.open_session(user_id, trigger_context)
        logger.info("conversation_open user=%s conv=%s", user_id, state.conversation_id)
        return state.conversation_id

    def close(self, conversation_id: str) -> None:
        self._manager.close_session(conversation_id)
        logger.info("conversation_close conv=%s", conversation_id)

    async def close_and_persist(
        self,
        conversation_id: str,
        db: Optional[AsyncSession] = None,
    ) -> None:
        """
        Close the conversation and persist any extracted lifestyle signals
        as HabitEvent rows for prescriber / assessor consumption.

        Also persists extracted UserFacts to the user_facts table.
        """
        final_state = self._manager.close_session(conversation_id)
        logger.info("conversation_close conv=%s", conversation_id)

        if final_state is None or db is None:
            return

        uid = parse_uuid(final_state.user_id)
        if uid is None:
            return

        # ── Persist habit signals ──────────────────────────────────────────────
        signals = final_state.accumulated_signals
        if signals:
            now = datetime.now(UTC)
            for signal in signals:
                event_type = _SIGNAL_TO_EVENT_TYPE.get(signal, signal[:40])
                row = HabitEvent(
                    user_id=uid,
                    ts=now,
                    event_type=event_type,
                    source="conversation",
                )
                db.add(row)
            try:
                await db.commit()
                logger.info(
                    "habit_events_persisted conv=%s count=%d", conversation_id, len(signals)
                )
            except Exception:
                logger.exception("Failed to persist habit events for conv=%s", conversation_id)
                await db.rollback()

        # ── Persist extracted user facts ───────────────────────────────────────
        raw_facts = final_state.accumulated_facts
        if raw_facts:
            try:
                existing = await _profile_svc.load_facts(db, uid)
                existing_by_key = {
                    f"{f.category}.{f.fact_key}": f.fact_id
                    for f in existing
                    if f.fact_key
                }
                for fact_dict in raw_facts:
                    dedup_key = f"{fact_dict.get('category')}.{fact_dict.get('fact_key')}"
                    if dedup_key in existing_by_key:
                        # Bump confidence on re-mention
                        await _profile_svc.bump_fact_confidence(
                            db, existing_by_key[dedup_key], delta=0.2
                        )
                    else:
                        from profile.fact_extractor import ExtractedFact
                        ef = ExtractedFact(
                            category=fact_dict["category"],
                            fact_text=fact_dict["fact_text"],
                            fact_key=fact_dict.get("fact_key"),
                            fact_value=fact_dict.get("fact_value"),
                            polarity=fact_dict.get("polarity", "neutral"),
                            confidence=fact_dict.get("confidence", 0.5),
                        )
                        await _profile_svc.log_fact(
                            db,
                            uid,
                            ef,
                            source_conversation_id=parse_uuid(conversation_id),
                        )
                logger.info(
                    "facts_persisted conv=%s count=%d", conversation_id, len(raw_facts)
                )
            except Exception:
                logger.exception("Failed to persist facts for conv=%s", conversation_id)

    async def _persist_high_conf_facts_mid_turn(
        self,
        db: AsyncSession,
        uid: uuid.UUID,
        conversation_id: str,
        extracted_facts: list,
    ) -> None:
        """Persist facts with confidence >= 0.8 so later turns see them in KNOWN FACTS."""
        if not extracted_facts:
            return
        conv_uuid = parse_uuid(conversation_id)
        try:
            existing = await _profile_svc.load_facts(db, uid)
            existing_by_key = {
                f"{f.category}.{f.fact_key}": f.fact_id
                for f in existing
                if f.fact_key
            }
            for ef in extracted_facts:
                if ef.confidence < _FACT_PERSIST_MIN_CONFIDENCE:
                    continue
                dedup_key = f"{ef.category}.{ef.fact_key}"
                if ef.fact_key and dedup_key in existing_by_key:
                    fid = existing_by_key[dedup_key]
                    if fid:
                        await _profile_svc.bump_fact_confidence(
                            db, uuid.UUID(fid), delta=0.2
                        )
                else:
                    await _profile_svc.log_fact(
                        db, uid, ef, source_conversation_id=conv_uuid
                    )
            logger.debug(
                "mid_turn facts persisted conv=%s (high-confidence facts from this message)",
                conversation_id,
            )
        except Exception:
            logger.exception(
                "mid_conversation fact persist failed conv=%s", conversation_id
            )

    # ── Turn processing ────────────────────────────────────────────────────────

    async def process_turn(
        self,
        conversation_id: str,
        user_message:    str,
        model_service:   ModelService,
        db:              Optional[AsyncSession] = None,
    ) -> TurnResult:
        """
        Process one user message and return the coach reply + any plan updates.
        Persists both sides of the turn to DB if `db` is provided.
        """
        started = perf_counter()
        state = self._store.get(conversation_id)
        if state is None:
            raise ValueError(f"conversation {conversation_id} not found")

        user_id = state.user_id
        fp      = await model_service.get_fingerprint(user_id) or PersonalFingerprint()
        profile = model_service.get_profile_from_fingerprint(fp)
        self._scratch_profile = profile

        # ── Phase 4: assemble live physio data before building ctx ─────────────
        uid = parse_uuid(user_id)
        assembled: Optional[AssembledContext] = None
        avoid_items_raw: list[dict] = []
        psych_insight: Optional[str] = None
        uup_narrative: Optional[str] = None
        user_facts_lines: list[str] = []
        engagement_tier: Optional[str] = None
        if db is not None and uid is not None:
            try:
                assemble_started = perf_counter()
                assembled = await assemble_for_user(db, uid)
                uup = await _profile_svc.load_unified_profile(db, uid)
                if uup is not None and uup.avoid_items:
                    avoid_items_raw = [
                        {"slug_or_label": a.slug_or_label, "reason": a.reason}
                        for a in uup.avoid_items
                    ]
                if assembled is not None:
                    psych_insight = assembled.psych_insight
                    uup_narrative = assembled.coach_narrative
                    user_facts_lines = list(assembled.user_facts or [])
                    engagement_tier = assembled.engagement_tier
                logger.info(
                    "perf assemble_for_user conv=%s user=%s duration_ms=%.2f",
                    conversation_id,
                    user_id,
                    (perf_counter() - assemble_started) * 1000.0,
                )
            except Exception:
                logger.warning(
                    "DataAssembler failed for user=%s — proceeding without physio", user_id
                )
                assembled = None
                avoid_items_raw = []
                psych_insight = None
                uup_narrative = None
                user_facts_lines = []
                engagement_tier = None

        # Extract today scores from assembled trajectory (most recent day)
        _net_bal: Optional[float] = None
        _stress_sc: Optional[int] = None
        _recovery_sc: Optional[int] = None
        _rx_readiness: float = 50.0
        if assembled is not None and assembled.daily_trajectory:
            _latest = assembled.daily_trajectory[-1]
            _net_bal = _latest.get("net_balance")
            raw_sl   = _latest.get("stress_load")
            raw_wr   = _latest.get("waking_recovery")
            _stress_sc   = int(round(raw_sl))   if raw_sl   is not None else None
            _recovery_sc = int(round(raw_wr))   if raw_wr   is not None else None
            if _latest.get("readiness_score") is not None:
                try:
                    _rx_readiness = float(_latest["readiness_score"])
                except (TypeError, ValueError):
                    pass
        # ── end Phase 4 assembly ───────────────────────────────────────────────

        # Pre-extract + persist high-confidence facts before context build so
        # KNOWN FACTS reflects DB state; pass pre_extraction to avoid duplicate extraction.
        pre_extraction = None
        if db is not None and uid is not None:
            existing_sigs = list(state.accumulated_signals)
            pre_extraction = extract_signals_from_message(
                user_message, existing_signals=existing_sigs
            )
            await self._persist_high_conf_facts_mid_turn(
                db, uid, conversation_id, pre_extraction.extracted_facts
            )
            try:
                recs = await _profile_svc.load_facts(db, uid, min_confidence=0.7)
                user_facts_lines = [r.fact_text for r in recs[:10]]
            except Exception:
                logger.warning("reload user_facts after mid-turn persist failed")

        def _build_ctx(
            last_user_said:        Optional[str],
            conversation_summary: Optional[str],
            extracted_signals:     Optional[list[str]],
            newly_extracted_facts: Optional[list[str]] = None,
        ) -> CoachContext:
            signals  = [HabitSignal(event_type=s, source="conversation") for s in (extracted_signals or [])]
            prx      = compute_daily_prescription(
                profile, readiness_score=_rx_readiness, habit_signals=signals
            )
            tone     = select_tone(profile)
            return build_coach_context(
                profile, fp,
                trigger_type="conversation_turn",
                tone=tone,
                prescription=prx,
                last_user_said=last_user_said,
                conversation_summary=conversation_summary,
                extracted_signals=extracted_signals,
                net_balance=_net_bal,
                stress_score=_stress_sc,
                recovery_score=_recovery_sc,
                psych_insight=psych_insight,
                uup_narrative=uup_narrative,
                user_facts=user_facts_lines,
                engagement_tier=engagement_tier,
                avoid_items=avoid_items_raw,
                newly_extracted_facts=newly_extracted_facts,
            )

        manager_started = perf_counter()
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    self._manager.process_turn,
                    conversation_id,
                    user_message,
                    _build_ctx,
                    pre_extraction=pre_extraction,
                ),
                timeout=_COACH_TURN_TIMEOUT_S,
            )
        except TimeoutError:
            logger.warning("conversation_turn_timeout conv=%s timeout_s=%.1f", conversation_id, _COACH_TURN_TIMEOUT_S)
            result = TurnResult(
                reply_payload={
                    "reply": "I am still processing your context. Please retry in a moment.",
                    "follow_up_question": None,
                },
                session_open=False,
                conversation_id=conversation_id,
                turn_index=state.turn_index,
            )
        logger.info(
            "perf conversation_manager_turn conv=%s duration_ms=%.2f",
            conversation_id,
            (perf_counter() - manager_started) * 1000.0,
        )

        # Persist to DB
        if db is not None:
            # uid was already computed above during assembly; reuse it
            if uid is not None:
                user_event = ConversationEvent(
                    user_id=uid, role="user", content=user_message,
                )
                coach_reply_text = result.reply_payload.get("reply", "") if result.reply_payload else ""
                coach_event = ConversationEvent(
                    user_id=uid, role="coach",
                    content=coach_reply_text or result.handoff_message,
                    plan_adjusted=False,
                )
                db.add(user_event)
                db.add(coach_event)
                await db.commit()

        logger.debug(
            "conversation_turn conv=%s session_open=%s",
            conversation_id, result.session_open,
        )
        logger.info(
            "perf conversation_turn_total conv=%s duration_ms=%.2f",
            conversation_id,
            (perf_counter() - started) * 1000.0,
        )
        return result

    # ── History ───────────────────────────────────────────────────────────────

    def get_active_conversation(self, user_id: str) -> Optional[str]:
        """Return the conversation_id of an open session for this user, if any."""
        for state in self._store._store.values():
            if state.user_id == user_id:
                return state.conversation_id
        return None
