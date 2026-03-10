"""
config/model.py

Personal model and onboarding parameters.
"""

from pydantic_settings import BaseSettings


class ModelConfig(BaseSettings):

    # ── Onboarding / Baseline ─────────────────────────────────────────────────
    # downstream: model/baseline_builder

    # Minimum hours of band wear before a first snapshot is shown to the user
    BASELINE_FIRST_SNAPSHOT_HOURS: int = 6

    # Hours of data before a full archetype can be declared with confidence
    BASELINE_FULL_HOURS: int = 48

    # Minimum valid sessions in baseline window before archetype is confident
    BASELINE_MIN_VALID_SESSIONS: int = 3

    # ── Rolling Distributions ─────────────────────────────────────────────────
    # downstream: model/personal_distributions, outcomes/weekly_outcomes
    # Must match — if outcomes window changes, distributions window must too
    DISTRIBUTION_ROLLING_DAYS: int = 30

    # Minimum RMSSD readings before personal floor/ceiling are considered stable
    DISTRIBUTION_MIN_READINGS: int = 20

    # ── Archetype Classification ──────────────────────────────────────────────
    # downstream: archetypes/classifier
    ARCHETYPE_MIN_HOURS: int = 24
    ARCHETYPE_CONFIDENCE_THRESHOLD: float = 0.65

    # Number of days between archetype evolution checks
    # (archetype drift is slow — checking daily is noise)
    ARCHETYPE_EVOLUTION_CHECK_DAYS: int = 7

    # ── Interoception Gap ─────────────────────────────────────────────────────
    # downstream: model/interoception_gap, archetypes/classifier (Suppressor)
    # Pearson r between subjective stress scores and objective RMSSD deviations
    # Value below threshold → Suppressor archetype signal
    INTEROCEPTION_GAP_SUPPRESSOR_THRESHOLD: float = -0.3

    # ── Subjective Check-in ───────────────────────────────────────────────────
    # downstream: api/routers/plan (scheduling), model/interoception_gap
    CHECKIN_CADENCE_DAYS: int = 3

    # ── Habit Event Correlation ───────────────────────────────────────────────
    # downstream: model/habits
    # How many hours after a habit event do we correlate with HRV impact
    HABIT_CORRELATION_WINDOW_HOURS: int = 18

    model_config = {"env_prefix": "ZENFLOW_MODEL_", "extra": "ignore"}
