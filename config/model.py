"""
config/model.py

Personal model and onboarding parameters.
"""

from pydantic_settings import BaseSettings


class ModelConfig(BaseSettings):

    # ── Onboarding / Baseline ─────────────────────────────────────────────────
    # downstream: model/baseline_builder

    # Minimum hours of band wear before first provisional scores shown to user
    # (with "Learning your baseline" label)
    BASELINE_FIRST_SNAPSHOT_HOURS: int = 3   # was 6

    # Hours of data (~3 days continuous wear) before baseline is considered stable
    # After this point, calibration_locked=True and floor/ceiling/morning_avg freeze.
    BASELINE_FULL_HOURS: int = 72            # was 48 — now 3 days

    # Calibration_days threshold at which the fingerprint is frozen
    # (passed as calibration_locked=True to update_rmssd_stats)
    BASELINE_STABLE_DAYS: int = 3

    # Minimum valid sessions in baseline window before archetype is confident
    BASELINE_MIN_VALID_SESSIONS: int = 3

    # ── Capacity Growth Trigger ───────────────────────────────────────────────
    # downstream: model/fingerprint_updater, jobs/nightly_rebuild

    # Minimum % range growth required before considering a capacity increase
    # e.g. 10.0 means new_range must be > old_range * 1.10
    CAPACITY_GROWTH_THRESHOLD_PCT: float = 10.0

    # Number of consecutive days the growth condition must hold before triggering
    CAPACITY_GROWTH_CONFIRM_DAYS: int = 7

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
