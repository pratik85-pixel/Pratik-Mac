"""
coach/conversation.py

Live conversation turn-taking state machine.

Design
------
Manages the lifecycle of a multi-turn coaching conversation.
Integrates: memory_store, safety_filter, conversation_extractor, coach_api.

Session lifecycle:
    open  → turn(s) → close

Closes when:
    - User says goodbye / dismisses
    - 5 turns reached (hard cap for context management)
    - follow_up_question is None in LLM output
    - Safety filter fires (immediate)

Turn flow per message:
    1. Screen user input via safety_filter
    2. Run conversation_extractor (parallel — does not block main reply)
    3. Build updated CoachContext with rolling summary
    4. Call coach_api.generate_response()
    5. Screen LLM output via safety_filter
    6. Advance turn, update rolling summary
    7. Check close conditions
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from coach.memory_store import MemoryStore, ConversationState
from coach.safety_filter import screen_text
from coach.conversation_extractor import extract_signals_from_message


# ── Conversation constants ────────────────────────────────────────────────────

MAX_TURNS = 5
_CLOSE_KEYWORDS = {
    "bye", "goodbye", "thanks", "thank you", "that's all", "thats all",
    "done", "ok thanks", "okay thanks", "i'm good", "im good", "got it",
}

_SUMMARY_TRIGGER_TURN = 3   # after this many turns, compress history to rolling summary


# ── TurnResult ────────────────────────────────────────────────────────────────

@dataclass
class TurnResult:
    """
    Result of a single conversation turn.

    reply_payload — cleaned output dict from coach_api
    session_open  — False means the conversation should be closed by the caller
    safety_fired  — True if a safety trigger occurred
    handoff_message — populated when safety_fired is True
    """
    reply_payload:   dict
    session_open:    bool
    safety_fired:    bool       = False
    handoff_message: str        = ""
    conversation_id: str        = ""
    turn_index:      int        = 0


# ── ConversationManager ───────────────────────────────────────────────────────

class ConversationManager:
    """
    Manages the full lifecycle of a live coaching conversation.

    Usage
    -----
    manager = ConversationManager(memory_store, coach_api_fn)
    state = manager.open_session(user_id, trigger_context)
    result = manager.process_turn(state.conversation_id, user_message, build_context_fn)
    if not result.session_open:
        manager.close_session(state.conversation_id)
    """

    def __init__(
        self,
        store: MemoryStore,
        coach_api_fn,  # callable: (CoachContext) -> dict
    ) -> None:
        self._store = store
        self._coach_api = coach_api_fn

    # ── Session lifecycle ─────────────────────────────────────────────────────

    def open_session(
        self,
        user_id: str,
        trigger_context: str = "",
    ) -> ConversationState:
        """Open a new conversation and return its initial state."""
        return self._store.create_session(user_id, trigger_context)

    def close_session(self, conversation_id: str) -> Optional[ConversationState]:
        """Close the session and return the final state for archiving."""
        return self._store.close_session(conversation_id)

    # ── Turn processing ───────────────────────────────────────────────────────

    def process_turn(
        self,
        conversation_id: str,
        user_message: str,
        build_context_fn,
    ) -> TurnResult:
        """
        Process a single user message and return the coach reply.

        Parameters
        ----------
        conversation_id : str
            Active session ID.
        user_message : str
            Raw user message text.
        build_context_fn : callable
            Provided by caller. Signature:
            (last_user_said, conversation_summary, extracted_signals) -> CoachContext

        Returns
        -------
        TurnResult
        """
        state = self._store.get(conversation_id)
        if state is None:
            return TurnResult(reply_payload={}, session_open=False)

        # Safety check — if already latched, close immediately
        if state.safety_triggered:
            return TurnResult(
                reply_payload   = {},
                session_open    = False,
                safety_fired    = True,
                handoff_message = (
                    "Please reach out to a crisis line. Text or call 988 (US) "
                    "or 116 123 (UK Samaritans)."
                ),
                conversation_id = conversation_id,
                turn_index      = state.turn_index,
            )

        # 1. Screen user input
        safety = screen_text(user_message)
        if not safety.is_safe:
            self._store.latch_safety(conversation_id)
            return TurnResult(
                reply_payload   = {},
                session_open    = False,
                safety_fired    = True,
                handoff_message = safety.handoff_message,
                conversation_id = conversation_id,
                turn_index      = state.turn_index,
            )

        # 2. Extract signals + facts (non-blocking — runs before LLM call)
        extraction = extract_signals_from_message(
            user_message,
            existing_signals=state.accumulated_signals,
        )
        for label in extraction.signal_labels:
            self._store.add_signal(conversation_id, label)
        if extraction.extracted_facts:
            self._store.add_facts(
                conversation_id,
                [
                    {
                        "category":  f.category,
                        "fact_text": f.fact_text,
                        "fact_key":  f.fact_key,
                        "fact_value": f.fact_value,
                        "polarity":  f.polarity,
                        "confidence": f.confidence,
                    }
                    for f in extraction.extracted_facts
                ],
            )

        # 3. Build context (caller-provided — has access to full profile + fingerprint)
        ctx = build_context_fn(
            last_user_said       = user_message,
            conversation_summary = state.rolling_summary or None,
            extracted_signals    = state.accumulated_signals,
        )

        # 4. Generate response
        reply_payload = self._coach_api(ctx)

        # 5. Screen LLM output
        reply_text = reply_payload.get("reply", "") or ""
        reply_safety = screen_text(reply_text)
        if not reply_safety.is_safe:
            self._store.latch_safety(conversation_id)
            return TurnResult(
                reply_payload   = {},
                session_open    = False,
                safety_fired    = True,
                handoff_message = reply_safety.handoff_message,
                conversation_id = conversation_id,
                turn_index      = state.turn_index,
            )

        # 6. Advance turn
        self._store.advance_turn(conversation_id)
        state = self._store.get(conversation_id)

        # 7. Update rolling summary after SUMMARY_TRIGGER_TURN
        if state.turn_index >= _SUMMARY_TRIGGER_TURN:
            prev = state.rolling_summary or ""
            new_fragment = f"Turn {state.turn_index}: User said: {user_message[:120]}"
            updated = (prev + " " + new_fragment).strip()
            # Truncate to ~300 words
            words = updated.split()
            if len(words) > 300:
                updated = " ".join(words[-300:])
            self._store.update_summary(conversation_id, updated)

        # 8. Determine close condition
        follow_up = reply_payload.get("follow_up_question")
        session_open = _should_keep_open(
            state         = state,
            user_message  = user_message,
            follow_up     = follow_up,
        )

        return TurnResult(
            reply_payload   = reply_payload,
            session_open    = session_open,
            safety_fired    = False,
            conversation_id = conversation_id,
            turn_index      = state.turn_index,
        )


# ── Close condition logic ─────────────────────────────────────────────────────

def _should_keep_open(
    state: ConversationState,
    user_message: str,
    follow_up,
) -> bool:
    """Returns True if the conversation should remain open."""
    # Hard cap
    if state.turn_index >= MAX_TURNS:
        return False

    # LLM chose to close
    if follow_up is None:
        return False

    # User dismissed
    user_lower = user_message.lower().strip().rstrip("!.?")
    if user_lower in _CLOSE_KEYWORDS:
        return False

    return True
