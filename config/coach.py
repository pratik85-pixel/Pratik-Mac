"""
config/coach.py

AI coach and conversation parameters.
"""

from pydantic_settings import BaseSettings


class CoachConfig(BaseSettings):

    # ── LLM ───────────────────────────────────────────────────────────────────
    # downstream: coach/coach_api
    LLM_MODEL: str = "gpt-4o"
    LLM_TEMPERATURE: float = 0.7
    LLM_MAX_TOKENS: int = 400

    # Maximum tokens allowed for the full context payload we send the LLM
    # Keep this well within model limits to leave room for the response
    LLM_MAX_CONTEXT_TOKENS: int = 3000

    # ── Tone Selection ────────────────────────────────────────────────────────
    # downstream: coach/tone_selector

    # Compassion tone when readiness score (0–100) falls below this
    TONE_COMPASSION_READINESS_THRESHOLD: int = 60

    # Celebrate tone when a milestone delta exceeds these minimums
    TONE_CELEBRATE_COHERENCE_DELTA: float = 0.15
    TONE_CELEBRATE_ARC_IMPROVEMENT_PCT: float = 0.20

    # Warn tone when RMSSD drops below personal average by this fraction
    TONE_WARN_RMSSD_DROP_PCT: float = 0.25

    # ── Conversation ──────────────────────────────────────────────────────────
    # downstream: coach/memory_store, coach/context_builder
    # How many past conversation turns to include in LLM context
    COACH_CONTEXT_HISTORY_TURNS: int = 5

    # downstream: coach/conversation (max session length before automatic close)
    CONVERSATION_MAX_TURNS: int = 10

    # ── Milestones ────────────────────────────────────────────────────────────
    # downstream: coach/milestone_detector
    MILESTONE_MIN_ARC_IMPROVEMENT_PCT: float = 0.20
    MILESTONE_MIN_COHERENCE_DELTA: float = 0.15
    MILESTONE_MIN_RESILIENCE_DELTA: int = 10

    # ── Safety Filter ─────────────────────────────────────────────────────────
    # downstream: coach/safety_filter
    # Model used for safety classification — cheaper/faster than main coach model
    SAFETY_MODEL: str = "gpt-4o-mini"

    # ── Nudge Cap ─────────────────────────────────────────────────────────────
    # downstream: api/routers/coach (nudge-check endpoint)
    # Max coach nudge messages allowed within a rolling 4-hour window.
    # Prevents repeated nudge spam if the app polls frequently.
    NUDGE_CAP_PER_4H: int = 2

    # Earliest IST hour at which nudge-check may return should_nudge=True (10:00)
    NUDGE_WINDOW_START_HOUR_IST: int = 10

    # Latest IST hour at which nudge-check may return should_nudge=True (20:00)
    NUDGE_WINDOW_END_HOUR_IST: int = 20

    # Earliest IST hour for night-closure (21:30 → stored as 21, checked with minute)
    NIGHT_CLOSURE_HOUR_IST: int = 21
    NIGHT_CLOSURE_MINUTE_IST: int = 30

    model_config = {"env_prefix": "ZENFLOW_COACH_", "extra": "ignore"}
