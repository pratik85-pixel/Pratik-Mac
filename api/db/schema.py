"""
api/db/schema.py

SQLAlchemy ORM models.

All tables store config_version so outcomes computed under different threshold
sets can be correctly interpreted or recalculated.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, Date, DateTime, Float, ForeignKey,
    Integer, String, Text, JSON, Index
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


# ── Users ──────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    name          = Column(String(120), nullable=False)
    email         = Column(String(255), unique=True, nullable=True)

    # Onboarding answers (raw — used to seed initial archetype hypothesis)
    onboarding    = Column(JSON, nullable=True)

    # Archetype (updated by archetype_classifier on schedule)
    archetype_primary   = Column(String(40), nullable=True)
    archetype_secondary = Column(String(40), nullable=True)
    archetype_confidence= Column(JSON, nullable=True)  # {"wire": 0.72, ...}
    archetype_updated_at= Column(DateTime(timezone=True), nullable=True)

    # Current training level (1–4)
    training_level = Column(Integer, default=1)
    level_updated_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    sessions       = relationship("Session", back_populates="user")
    personal_model = relationship("PersonalModel", back_populates="user", uselist=False)
    habits         = relationship("UserHabits", back_populates="user", uselist=False)
    check_ins      = relationship("CheckIn", back_populates="user")
    coach_messages = relationship("CoachMessage", back_populates="user")
    psych_profile    = relationship("UserPsychProfile", back_populates="user", uselist=False)
    unified_profile  = relationship("UserUnifiedProfile", back_populates="user", uselist=False)
    user_facts       = relationship("UserFact", back_populates="user")


# ── Sessions ───────────────────────────────────────────────────────────────────

class Session(Base):
    __tablename__ = "sessions"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id      = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    started_at   = Column(DateTime(timezone=True), nullable=False)
    ended_at     = Column(DateTime(timezone=True), nullable=True)

    # Context: "session" | "background" | "sleep" | "morning_read"
    context      = Column(String(30), nullable=False, default="session")

    # Practice type: "resonance" | "box" | "extended_exhale" | "478" | "body_scan"
    practice_type = Column(String(40), nullable=True)

    # Outcome metrics (computed by outcomes/session_outcomes.py post-session)
    session_score        = Column(Float, nullable=True)   # 0–100
    coherence_avg        = Column(Float, nullable=True)   # 0.0–1.0
    zone_1_seconds       = Column(Float, nullable=True)
    zone_2_seconds       = Column(Float, nullable=True)
    zone_3_seconds       = Column(Float, nullable=True)
    zone_4_seconds       = Column(Float, nullable=True)
    rmssd_pre            = Column(Float, nullable=True)   # ms
    rmssd_post           = Column(Float, nullable=True)   # ms
    pi_pre               = Column(Float, nullable=True)   # Perfusion Index
    pi_post              = Column(Float, nullable=True)
    is_hardmode          = Column(Boolean, default=False)

    # Config version this session was computed under
    config_version       = Column(Integer, nullable=False, default=1)

    user = relationship("User", back_populates="sessions")
    metrics = relationship("Metric", back_populates="session")


# ── Metrics (time-series) ──────────────────────────────────────────────────────

class Metric(Base):
    """
    One row per computed metric value.
    Kept as a log — personal model reads from this to build distributions.
    """
    __tablename__ = "metrics"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id     = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    session_id  = Column(UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=True)
    ts          = Column(DateTime(timezone=True), nullable=False)

    # Metric identity
    name        = Column(String(40), nullable=False)   # "rmssd" | "coherence" | "pi" | ...
    value       = Column(Float, nullable=False)
    confidence  = Column(Float, nullable=False)         # 0.0–1.0

    # Context tag from bridge: "session" | "background" | "sleep" | "morning_read"
    context     = Column(String(30), nullable=False)

    session = relationship("Session", back_populates="metrics")

    __table_args__ = (
        Index("ix_metrics_user_ts", "user_id", "ts"),
        Index("ix_metrics_user_name_ts", "user_id", "name", "ts"),
    )


# ── Personal Model (versioned fingerprint) ─────────────────────────────────────

class PersonalModel(Base):
    """
    Current physiological fingerprint for a user.
    One row per user — updated in-place, previous state captured in ModelSnapshot.
    """
    __tablename__ = "personal_models"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id     = Column(UUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False)
    updated_at  = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    version     = Column(Integer, default=1)

    # RMSSD distribution (personal, not population-normalised)
    rmssd_floor     = Column(Float, nullable=True)   # ms — personal minimum
    rmssd_ceiling   = Column(Float, nullable=True)   # ms — personal maximum
    rmssd_weekday_avg = Column(Float, nullable=True)
    rmssd_weekend_avg = Column(Float, nullable=True)
    rmssd_morning_avg = Column(Float, nullable=True)

    # Recovery arc
    recovery_arc_mean_hours  = Column(Float, nullable=True)
    recovery_arc_fast_hours  = Column(Float, nullable=True)
    recovery_arc_slow_hours  = Column(Float, nullable=True)

    # Coherence trainability
    coherence_floor          = Column(Float, nullable=True)  # first session avg
    coherence_trainability   = Column(String(20), nullable=True)  # "low"|"moderate"|"high"

    # Stress fingerprint
    stress_peak_day          = Column(String(12), nullable=True)  # "wednesday"
    stress_peak_hour         = Column(Integer, nullable=True)     # 0–23

    # Compliance
    compliance_best_window   = Column(String(5), nullable=True)   # "19:00"

    # Interoception gap (Pearson r — subjective vs objective alignment)
    interoception_gap        = Column(Float, nullable=True)

    # RSA trainability
    rsa_resting_avg          = Column(Float, nullable=True)
    rsa_guided_avg           = Column(Float, nullable=True)
    rsa_trainability_delta   = Column(Float, nullable=True)   # guided − resting
    rsa_trainability         = Column(String(20), nullable=True)  # "low"|"moderate"|"high"

    # Sleep proxy
    sleep_recovery_efficiency  = Column(Float, nullable=True)  # morning/evening RMSSD ratio
    overnight_rmssd_delta_avg  = Column(Float, nullable=True)  # morning − pre-sleep avg

    # Activity × coherence map
    natural_elevators          = Column(JSON, nullable=True)   # list of ActivityProfile dicts
    coherence_drains           = Column(JSON, nullable=True)   # list of ActivityProfile dicts
    best_natural_window_start  = Column(String(5), nullable=True)   # "HH:MM"
    worst_natural_window_start = Column(String(5), nullable=True)

    # LF/HF sleep comparison
    lf_hf_resting            = Column(Float, nullable=True)
    lf_hf_sleep              = Column(Float, nullable=True)

    # ── Stress/Recovery capacity baseline ──────────────────────────────────
    # Active personal floor used for stress load normalization.
    # Updates monthly (or when floor shifts >10% for 7+ consecutive days).
    stress_capacity_floor_rmssd = Column(Float, nullable=True)

    # Increments each time stress_capacity_floor_rmssd updates.
    # DailyStressSummary stores this at computation time for recompute support.
    capacity_version            = Column(Integer, default=0)

    # Rolling 14-day median wake/sleep times (from bridge context transitions).
    # "HH:MM" format. Fall back to morning read anchor if not populated.
    typical_wake_time           = Column(String(5), nullable=True)   # "07:15"
    typical_sleep_time          = Column(String(5), nullable=True)   # "23:00"

    # Full fingerprint as JSON (for fields not worth individual columns)
    fingerprint_json         = Column(JSON, nullable=True)

    # PRF (Personal Resonance Frequency) — found during resonance sessions
    # Stored as breaths per minute (e.g. 6.5).  None = not yet found.
    prf_bpm                  = Column(Float, nullable=True)
    # "PRF_UNKNOWN" | "PRF_FOUND" | "PRF_CONFIRMED"
    prf_status               = Column(String(20), nullable=True, default="PRF_UNKNOWN")

    # ── Phase 10: Calibration lock ────────────────────────────────────────────
    # Set when calibration_days reaches BASELINE_STABLE_DAYS (3).
    # Once set, floor/ceiling/morning_avg are frozen — no more EWM updates.
    # Capacity grows only via explicit capacity-increase trigger (Step 6).
    calibration_locked_at    = Column(DateTime(timezone=True), nullable=True)

    # ── Step 6: Capacity growth streak ───────────────────────────────────────
    # Incremented each day yesterday's peak valid RMSSD exceeds
    # rmssd_ceiling * (1 + CAPACITY_GROWTH_THRESHOLD_PCT / 100).
    # Resets to 0 if threshold not met for a day (band worn).
    # Triggers re-lock when it reaches CAPACITY_GROWTH_CONFIRM_DAYS (7).
    capacity_growth_streak   = Column(Integer, default=0, nullable=True)

    # ── Sleep scoring v2: personal sleep baseline ─────────────────────────────
    # Populated by _run_calibration_batch() when band is worn overnight
    # (requires >= 12 sleep windows = 60 min). NULL until then.
    # Used as baseline for sleep recovery/stress scoring instead of waking avg.
    rmssd_sleep_avg          = Column(Float, nullable=True)   # median sleep RMSSD (ms)
    rmssd_sleep_ceiling      = Column(Float, nullable=True)   # P90 sleep RMSSD (ms)

    user = relationship("User", back_populates="personal_model")


class ModelSnapshot(Base):
    """Immutable historical snapshots of PersonalModel — one per update event."""
    __tablename__ = "model_snapshots"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id     = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    snapshot_at = Column(DateTime(timezone=True), server_default=func.now())
    model_version = Column(Integer, nullable=False)
    snapshot_json = Column(JSON, nullable=False)   # full fingerprint at that point in time


class CalibrationSnapshot(Base):
    """
    Audit record for each end-of-day calibration batch (Days 1–3).

    Written by `_run_calibration_batch()` in tracking_service.py.
    Never deleted after lock — used for production debugging and future
    ML training data. One row per day_number per user during calibration.
    """
    __tablename__ = "calibration_snapshots"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id     = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    snapshot_at = Column(DateTime(timezone=True), server_default=func.now())
    day_number  = Column(Integer, nullable=False)   # 1, 2, or 3

    # --- Raw values (before 3-pass artifact filter) ---
    rmssd_floor_raw       = Column(Float, nullable=True)
    rmssd_ceiling_raw     = Column(Float, nullable=True)
    rmssd_morning_avg_raw = Column(Float, nullable=True)

    # --- Clean values (after filter) ---
    rmssd_floor_clean       = Column(Float, nullable=True)
    rmssd_ceiling_clean     = Column(Float, nullable=True)
    rmssd_morning_avg_clean = Column(Float, nullable=True)

    # --- Filter stats ---
    windows_total    = Column(Integer, nullable=True)   # total windows considered
    windows_rejected = Column(Integer, nullable=True)   # rejected by artifact filter
    confidence       = Column(Float, nullable=True)     # 0.0–1.0

    # --- Outcome flags ---
    committed     = Column(Boolean, nullable=False, default=False)  # pushed to personal_model
    sanity_passed = Column(Boolean, nullable=False, default=True)   # morning_avg >= floor + 10% range

    # --- Sleep scoring v2 audit ---
    rmssd_sleep_avg_clean = Column(Float, nullable=True)    # sleep median from this day's windows
    sleep_windows_count   = Column(Integer, nullable=True)  # how many sleep windows were available

    __table_args__ = (
        Index("ix_calibration_snapshots_user_day", "user_id", "day_number"),
    )


# ── Habits ─────────────────────────────────────────────────────────────────────

class UserHabits(Base):
    __tablename__ = "user_habits"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id     = Column(UUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False)
    updated_at  = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    movement_enjoyed    = Column(JSON, nullable=True)  # ["running", "hiking"]
    exercise_frequency  = Column(String(30), nullable=True)
    alcohol             = Column(String(30), nullable=True)
    caffeine            = Column(String(30), nullable=True)
    smoking             = Column(String(20), nullable=True)
    sleep_schedule      = Column(String(20), nullable=True)
    typical_day         = Column(String(40), nullable=True)
    stress_drivers      = Column(JSON, nullable=True)
    decompress_via      = Column(JSON, nullable=True)

    user = relationship("User", back_populates="habits")


class HabitEvent(Base):
    """Runtime habit events — logged via conversation extractor or Apple/Health Connect."""
    __tablename__ = "habit_events"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id     = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    ts          = Column(DateTime(timezone=True), nullable=False)

    # "alcohol" | "exercise" | "late_night" | "stressful_event" | "caffeine" | "poor_sleep"
    event_type  = Column(String(40), nullable=False)
    severity    = Column(String(20), nullable=True)  # "light" | "moderate" | "heavy"
    source      = Column(String(20), nullable=False)  # "conversation" | "health_connect" | "manual"
    notes       = Column(Text, nullable=True)

    # HRV impact (filled in retrospectively by model/habits correlation job)
    rmssd_delta_next_morning = Column(Float, nullable=True)

    __table_args__ = (Index("ix_habit_events_user_ts", "user_id", "ts"),)


# ── Activity × Coherence Events ────────────────────────────────────────────────

class ActivityCoherenceEvent(Base):
    """
    One activity-tagged coherence reading.
    Populated when a coherence spike is detected or via end-of-day prompt.
    Used by activity_coherence_tracker to build the personal coherence map.
    """
    __tablename__ = "activity_coherence_events"

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id          = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    ts               = Column(DateTime(timezone=True), nullable=False)

    # Activity tag — key from ACTIVITY_TAGS dict in activity_coherence_tracker.py
    activity_tag     = Column(String(40), nullable=False)
    activity_label   = Column(String(100), nullable=True)

    coherence        = Column(Float, nullable=False)    # 0.0–1.0
    duration_minutes = Column(Float, nullable=True)
    confidence       = Column(Float, nullable=False)    # coherence measurement confidence

    # How the tag was collected
    # "passive_spike" | "eod_prompt" | "health_connect" | "conversation"
    source           = Column(String(30), nullable=False)
    notes            = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_activity_coherence_user_ts", "user_id", "ts"),
        Index("ix_activity_coherence_user_tag", "user_id", "activity_tag"),
    )


# ── Morning Reads ──────────────────────────────────────────────────────────────

class MorningRead(Base):
    """
    Structured 5-minute morning read — captured before phone/caffeine.
    This is the most important single data point per day.
    Contains the user's nervous system budget for the day.
    """
    __tablename__ = "morning_reads"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id      = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    read_date    = Column(DateTime(timezone=True), nullable=False)  # date of the read
    captured_at  = Column(DateTime(timezone=True), server_default=func.now())

    rmssd_ms     = Column(Float, nullable=True)
    rsa_power    = Column(Float, nullable=True)
    coherence    = Column(Float, nullable=True)
    lf_hf        = Column(Float, nullable=True)
    hr_bpm       = Column(Float, nullable=True)
    confidence   = Column(Float, nullable=False, default=0.0)

    # Day type assigned from this read
    # "green" | "yellow" | "red" (matched from ScoringConfig zones)
    day_type     = Column(String(10), nullable=True)

    # vs personal rmssd_morning_avg (percent above/below)
    vs_personal_avg_pct = Column(Float, nullable=True)

    config_version = Column(Integer, nullable=False, default=1)

    __table_args__ = (Index("ix_morning_reads_user_date", "user_id", "read_date"),)


# ── Check-ins (subjective) ─────────────────────────────────────────────────────

class CheckIn(Base):
    __tablename__ = "check_ins"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id     = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    # Three questions — 1 (poor) to 5 (excellent)
    reactivity  = Column(Integer, nullable=False)  # "How easily did small things irritate you?"
    focus       = Column(Integer, nullable=False)  # "How easy was it to concentrate?"
    recovery    = Column(Integer, nullable=False)  # "After stress, how quickly did you feel okay?"

    # Corresponding RMSSD on the same day (filled by model correlation job)
    rmssd_same_day = Column(Float, nullable=True)

    user = relationship("User", back_populates="check_ins")


# ── Coach Messages ─────────────────────────────────────────────────────────────

class CoachMessage(Base):
    __tablename__ = "coach_messages"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id     = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    # "morning_brief" | "post_session" | "nudge" | "milestone" | "conversation"
    message_type = Column(String(30), nullable=False)

    # Structured output from coach layer
    summary      = Column(Text, nullable=False)
    reason       = Column(Text, nullable=True)
    action       = Column(Text, nullable=True)
    encouragement = Column(Text, nullable=True)
    tone         = Column(String(20), nullable=True)  # "compassion"|"push"|"celebrate"|"warn"

    # User reaction (optional — tapped "helpful" / dismissed)
    user_reaction = Column(String(20), nullable=True)

    user = relationship("User", back_populates="coach_messages")


class ConversationEvent(Base):
    """Individual turns in a coach conversation."""
    __tablename__ = "conversation_events"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id     = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    ts          = Column(DateTime(timezone=True), server_default=func.now())

    role        = Column(String(10), nullable=False)   # "user" | "coach"
    content     = Column(Text, nullable=False)

    # Extracted signals (from conversation_extractor — coach turns only)
    extracted_events = Column(JSON, nullable=True)
    plan_adjusted    = Column(Boolean, default=False)


# ── Outcomes ───────────────────────────────────────────────────────────────────

class WeeklyOutcome(Base):
    __tablename__ = "weekly_outcomes"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id         = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    week_start      = Column(DateTime(timezone=True), nullable=False)
    computed_at     = Column(DateTime(timezone=True), server_default=func.now())
    config_version  = Column(Integer, nullable=False)

    resilience_avg          = Column(Float, nullable=True)  # 0–100
    resilience_delta        = Column(Float, nullable=True)  # vs previous week
    recovery_arc_avg_hours  = Column(Float, nullable=True)
    recovery_arc_delta      = Column(Float, nullable=True)
    sessions_completed      = Column(Integer, nullable=True)
    sessions_planned        = Column(Integer, nullable=True)
    zone3_total_minutes     = Column(Float, nullable=True)
    hardmode_sessions       = Column(Integer, nullable=True)

    report_json     = Column(JSON, nullable=True)  # full report card payload


class MonthlyOutcome(Base):
    __tablename__ = "monthly_outcomes"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id         = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    month_start     = Column(DateTime(timezone=True), nullable=False)
    computed_at     = Column(DateTime(timezone=True), server_default=func.now())
    config_version  = Column(Integer, nullable=False)

    # Deltas vs day-1 baseline
    resilience_vs_baseline      = Column(Float, nullable=True)
    recovery_arc_vs_baseline    = Column(Float, nullable=True)
    sleep_quality_vs_baseline   = Column(Float, nullable=True)
    coherence_vs_baseline       = Column(Float, nullable=True)

    # Subjective × objective correlation (Pearson r)
    interoception_correlation   = Column(Float, nullable=True)

    archetype_at_start  = Column(String(40), nullable=True)
    archetype_at_end    = Column(String(40), nullable=True)

    report_json         = Column(JSON, nullable=True)


# ── All-Day Tracking ───────────────────────────────────────────────────────────

class BackgroundWindow(Base):
    """
    5-minute aggregated HRV window during background (all-day) or sleep wear.

    One row per 5-minute period. The raw material for all tracking computations:
    stress_detector, recovery_detector, and daily_summarizer all read from this table.

    Invalid windows (confidence < 0.5 or n_beats < minimum) are stored with
    is_valid=False — they still contribute gap detection but are skipped in
    stress/recovery calculations.
    """
    __tablename__ = "background_windows"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id      = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    window_start = Column(DateTime(timezone=True), nullable=False)
    window_end   = Column(DateTime(timezone=True), nullable=False)

    # "background" | "sleep"
    context      = Column(String(20), nullable=False, default="background")

    # HRV metrics
    rmssd_ms     = Column(Float, nullable=True)
    hr_bpm       = Column(Float, nullable=True)
    lf_hf        = Column(Float, nullable=True)   # populated if freq-domain available
    confidence   = Column(Float, nullable=False, default=0.0)

    # Motion signals (for physical vs emotional stress classification)
    acc_mean     = Column(Float, nullable=True)   # mean ACC magnitude (g)
    gyro_mean    = Column(Float, nullable=True)   # mean Gyro magnitude

    # Data quality
    n_beats      = Column(Integer, nullable=False, default=0)
    artifact_rate = Column(Float, nullable=False, default=0.0)
    is_valid     = Column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("ix_bg_windows_user_start", "user_id", "window_start"),
        Index("ix_bg_windows_user_context", "user_id", "context"),
    )


class StressWindow(Base):
    """
    A detected continuous stress episode within a day's background stream.

    Detected by tracking/stress_detector.py when RMSSD breaches the
    personal morning average threshold for >= STRESS_MIN_WINDOWS consecutive windows.

    The tag field starts as None (auto-detected candidate). The user confirms
    via the Tag Sheet (nudge → tap). Auto-tagging populates it after sufficient
    pattern data (>= AUTOTAG_MIN_DAYS days with confirmed events).
    """
    __tablename__ = "stress_windows"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id      = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    started_at   = Column(DateTime(timezone=True), nullable=False)
    ended_at     = Column(DateTime(timezone=True), nullable=False)
    duration_minutes = Column(Float, nullable=False)

    # Signal depth
    rmssd_min_ms     = Column(Float, nullable=True)    # lowest RMSSD in the window
    suppression_pct  = Column(Float, nullable=True)    # nadir depth vs personal avg (0–1)

    # Contribution to daily stress load (% of day total, 0–100)
    stress_contribution_pct = Column(Float, nullable=True)

    # Raw area (for recompute under new baseline)
    suppression_area     = Column(Float, nullable=False, default=0.0)

    # Tagging
    # Confirmed user tag: "workout" | "work_calls" | "argument" | "walk" | "other" | ...
    tag          = Column(String(50), nullable=True)
    # Pre-confirmation system label: "physical_load_candidate" | "stress_event_candidate"
    tag_candidate = Column(String(50), nullable=True)
    # "auto_detected" | "user_confirmed" | "auto_tagged"
    tag_source   = Column(String(30), nullable=True, default="auto_detected")

    # Nudge tracking
    nudge_sent       = Column(Boolean, nullable=False, default=False)
    nudge_responded  = Column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("ix_stress_windows_user_start", "user_id", "started_at"),
    )


class RecoveryWindow(Base):
    """
    A detected continuous recovery episode.

    Detected by tracking/recovery_detector.py when RMSSD sustains at or above
    the personal morning average for >= RECOVERY_MIN_WINDOWS consecutive windows.

    Sleep recovery is always one RecoveryWindow covering the full sleep period.
    ZenFlow sessions are auto-tagged via session FK.
    Other daytime recovery windows prompt the user for tagging.
    """
    __tablename__ = "recovery_windows"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id      = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    started_at   = Column(DateTime(timezone=True), nullable=False)
    ended_at     = Column(DateTime(timezone=True), nullable=False)
    duration_minutes = Column(Float, nullable=False)

    # "background" | "sleep"
    context      = Column(String(20), nullable=False, default="background")

    # Signal depth
    rmssd_avg_ms = Column(Float, nullable=True)

    # Contribution to daily recovery score (% of day total)
    recovery_contribution_pct = Column(Float, nullable=True)

    # Raw area (for recompute)
    recovery_area = Column(Float, nullable=False, default=0.0)

    # Tagging
    # "sleep" | "zenflow_session" | "walk" | "exercise_recovery" | "recovery_window" | ...
    tag          = Column(String(50), nullable=True)
    # "auto_confirmed" | "user_confirmed" | "auto_tagged"
    tag_source   = Column(String(30), nullable=True)

    # FK to ZenFlow session if this recovery window overlaps one
    zenflow_session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=True)

    __table_args__ = (
        Index("ix_recovery_windows_user_start", "user_id", "started_at"),
    )


# ── Tag Pattern Model ──────────────────────────────────────────────────────────

class TagPatternModel(Base):
    """
    Per-user tag pattern model.

    One row per user.  Updated after each user tag confirmation and by the
    nightly auto-tag pass.  Stores the full model_json from
    tagging.tag_pattern_model.UserTagPatternModel.to_dict().
    """
    __tablename__ = "tag_pattern_models"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id      = Column(UUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False)
    updated_at   = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    version      = Column(Integer, default=1)

    # Full model serialised as JSON
    model_json   = Column(JSON, nullable=False, default=dict)

    # Sport stressors surfaced separately for fast CoachContext assembly
    # list[str] of activity slugs that consistently drive high stress
    sport_stressor_slugs = Column(JSON, nullable=True, default=list)

    # Number of distinct confirmed-event patterns
    patterns_built = Column(Integer, default=0)


# ── Daily Plan ─────────────────────────────────────────────────────────────────

class DailyPlan(Base):
    """
    One generated DailyPlan per user per calendar day.

    Generated by coach/prescriber.py every morning when a morning read arrives.
    Items are stored in items_json as a structured list.
    """
    __tablename__ = "daily_plans"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id     = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    plan_date   = Column(DateTime(timezone=True), nullable=False)   # date only
    generated_at = Column(DateTime(timezone=True), server_default=func.now())

    # Day type at time of generation
    day_type    = Column(String(10), nullable=True)   # "green" | "yellow" | "red"
    readiness_score = Column(Float, nullable=True)

    # Stage at generation time
    stage       = Column(Integer, nullable=True)

    # Plan items as JSON list of PlanItem dicts
    # {"slug", "display", "category", "priority", "duration_min", "reason"}
    items_json  = Column(JSON, nullable=False, default=list)

    # Prescriber rules that fired (for transparency / coach context)
    prescriber_notes = Column(JSON, nullable=True, default=list)

    # Overall adherence (computed retrospectively at day-close)
    adherence_pct   = Column(Float, nullable=True)

    __table_args__ = (
        Index("ix_daily_plans_user_date", "user_id", "plan_date"),
    )


class PlanDeviation(Base):
    """
    Logged deviation from a planned item.

    Created when a must_do or recommended item from DailyPlan is not completed,
    or when the user explicitly skips an item via the UI.
    """
    __tablename__ = "plan_deviations"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id      = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    plan_id      = Column(UUID(as_uuid=True), ForeignKey("daily_plans.id"), nullable=False)
    ts           = Column(DateTime(timezone=True), server_default=func.now())

    # Slug that was planned but not completed
    activity_slug = Column(String(50), nullable=False)

    # Priority that was skipped: "must_do" | "recommended" | "optional"
    priority      = Column(String(20), nullable=False)

    # Reason reported by user or inferred by coach
    # "time_constraint" | "low_energy" | "forgot" | "not_relevant" |
    # "technical_issue" | "other" | None (not yet captured)
    reason_category = Column(String(40), nullable=True)

    notes         = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_plan_deviations_user_ts", "user_id", "ts"),
    )


class DailyStressSummary(Base):
    """
    One row per user per calendar day.

    Finalized at day close (sleep detection or midnight fallback).
    Updated intraday with running stress/recovery totals.

    readiness_score is None until the morning read of the NEXT day arrives —
    it requires today's morning RMSSD to calibrate the prior score.
    """
    __tablename__ = "daily_stress_summaries"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id      = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    summary_date = Column(DateTime(timezone=True), nullable=False)   # date only
    computed_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at   = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Day boundary
    wake_ts      = Column(DateTime(timezone=True), nullable=True)
    sleep_ts     = Column(DateTime(timezone=True), nullable=True)
    wake_detection_method  = Column(String(30), nullable=True)
    sleep_detection_method = Column(String(30), nullable=True)
    waking_minutes         = Column(Float, nullable=True)

    # The three numbers (0–100)
    stress_load_score  = Column(Float, nullable=True)
    # DEPRECATED: never written, kept NULL. Waking recovery replaces this.
    recovery_score     = Column(Float, nullable=True)
    # DEPRECATED: never written, kept NULL. Net balance replaces readiness.
    readiness_score    = Column(Float, nullable=True)

    # "green" | "yellow" | "red" — sourced from MorningRead.day_type at day close
    day_type     = Column(String(10), nullable=True)

    # Credit-card model scores (Phase 10)
    waking_recovery_score = Column(Float, nullable=True)   # display only, clamped 0-100
    net_balance           = Column(Float, nullable=True)   # raw: recovery% - stress% + opening_balance

    # Continuous balance thread — carries across day boundaries
    opening_balance       = Column(Float, nullable=True, server_default='0')  # carried from prev closing_balance
    opening_recovery      = Column(Float, nullable=True)   # positive component: max(0, opening_balance) — prior surplus
    opening_stress        = Column(Float, nullable=True)   # negative component: min(0, opening_balance) — prior debt
    closing_balance       = Column(Float, nullable=True)   # = net_balance at day close

    # Raw unclamped percentages (for carry-forward integrity)
    stress_pct_raw        = Column(Float, nullable=True)   # stress_area / ns_capacity x 100 (unbounded)
    recovery_pct_raw      = Column(Float, nullable=True)   # recovery_area / ns_capacity x 100 (unbounded)

    # Raw inputs (for recompute under new baseline)
    raw_suppression_area       = Column(Float, nullable=False, default=0.0)
    raw_recovery_area_sleep    = Column(Float, nullable=False, default=0.0)
    raw_recovery_area_zenflow  = Column(Float, nullable=False, default=0.0)
    raw_recovery_area_daytime  = Column(Float, nullable=False, default=0.0)
    raw_recovery_area_waking   = Column(Float, nullable=False, default=0.0)
    # Single symmetric denominator: (ceiling - floor) x 960
    ns_capacity_used           = Column(Float, nullable=False, default=0.0)
    # Legacy field — kept for backward compat, equals ns_capacity_used
    max_possible_suppression   = Column(Float, nullable=False, default=0.0)
    # Sleep scoring v2: denominator used for recovery score (= range x 1440)
    ns_capacity_recovery       = Column(Float, nullable=True)

    # Baseline versioning
    capacity_floor_used = Column(Float, nullable=True)
    capacity_version    = Column(Integer, nullable=False, default=0)

    # Calibration metadata
    calibration_days = Column(Integer, nullable=False, default=0)
    is_estimated     = Column(Boolean, nullable=False, default=True)
    is_partial_data  = Column(Boolean, nullable=False, default=False)

    # Top contributors (nullable FK stubs)
    top_stress_window_id   = Column(UUID(as_uuid=True), ForeignKey("stress_windows.id"), nullable=True)
    top_recovery_window_id = Column(UUID(as_uuid=True), ForeignKey("recovery_windows.id"), nullable=True)

    __table_args__ = (
        Index("ix_daily_summaries_user_date", "user_id", "summary_date"),
    )


# ── Psychological Profile ─────────────────────────────────────────────────────

class UserPsychProfile(Base):
    """
    Inferred psychological / behavioural fingerprint.

    Built incrementally by psych/psych_profile_builder.py from:
      - StressWindow + RecoveryWindow tags
      - ActivityCoherenceEvent records
      - MoodLog + AnxietyEvent entries
      - DailyPlan + PlanDeviation (discipline)

    Never asks the user directly — everything is inferred or correlating
    physiological data with tagged events.
    """
    __tablename__ = "user_psych_profiles"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id    = Column(UUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # ── Social energy type ────────────────────────────────────────────────────
    # Inferred from mean RMSSD delta during/after social_time tagged windows.
    # Extroverts: delta > 0 (social recovers). Introverts: delta < 0 (social costs).
    social_energy_type   = Column(String(20), nullable=True)   # "introvert"|"ambivert"|"extrovert"|"unknown"
    social_hrv_delta_avg = Column(Float, nullable=True)         # mean readiness-score delta during social events
    social_event_count   = Column(Integer, default=0)           # n events used for inference

    # ── Anxiety sensitivity ───────────────────────────────────────────────────
    # 0.0 = stress causes minimal suppression relative to personal floor
    # 1.0 = stress causes extreme suppression
    anxiety_sensitivity  = Column(Float, nullable=True)   # 0.0–1.0

    # Top triggers ranked by (frequency × avg_severity).
    # [{"type": "deadline", "count": 5, "avg_severity": 0.7, "strength": 0.82}]
    top_anxiety_triggers = Column(JSON, nullable=True)

    # ── Activity ↔ physiology map ─────────────────────────────────────────────
    # [{"slug": "walking", "avg_recovery_lift": 14.2, "count": 8}] — expressed
    # as recovery-score points lifted, not raw RMSSD
    top_calming_activities = Column(JSON, nullable=True)
    # [{"slug": "work_sprint", "avg_stress_cost": 12.1, "count": 6}]
    top_stress_activities  = Column(JSON, nullable=True)

    # ── Recovery style ────────────────────────────────────────────────────────
    # Primary mode that reliably precedes recovery windows
    primary_recovery_style = Column(String(30), nullable=True)
    # "physical"|"social"|"solo_passive"|"nature"|"mindfulness"|"sleep"

    # ── Discipline index ──────────────────────────────────────────────────────
    # Rolling 28-day: (plans_completed / plans_generated) × streak_bonus
    discipline_index = Column(Float, nullable=True)   # 0–100
    streak_current   = Column(Integer, default=0)     # consecutive days on plan
    streak_best      = Column(Integer, default=0)     # all-time best streak

    # ── Mood baseline ─────────────────────────────────────────────────────────
    # Derived from MoodLog rolling 14-day average
    mood_baseline    = Column(String(20), nullable=True)  # "low"|"moderate"|"high"
    mood_score_avg   = Column(Float, nullable=True)       # 1.0–5.0

    # ── Interoception alignment ───────────────────────────────────────────────
    # Pearson r between MoodLog.mood_score and DailyStressSummary.readiness_score
    # High positive = user accurately feels their physiological state
    # Near-zero / negative = body and subjective don't match (key coaching signal)
    interoception_alignment = Column(Float, nullable=True)  # -1.0–1.0

    # ── Metadata ──────────────────────────────────────────────────────────────
    data_confidence  = Column(Float, nullable=True, default=0.0)  # 0–1
    last_computed_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="psych_profile")


class MoodLog(Base):
    """
    Daily subjective state log.

    Written at conversation close (extracted from chat) or via manual tap.
    One row per log entry — a user may log multiple times per day.
    The most recent log per day is used for interoception alignment.
    """
    __tablename__ = "mood_logs"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id    = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    log_date   = Column(DateTime(timezone=True), nullable=False)   # date of the entry
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Subjective state scores (1=terrible/none, 5=excellent/strong)
    mood_score    = Column(Integer, nullable=False)   # overall mood
    energy_score  = Column(Integer, nullable=True)    # physical energy
    anxiety_score = Column(Integer, nullable=True)    # anxiety level (5=very anxious)
    social_desire = Column(Integer, nullable=True)    # 1=want alone, 5=want people

    # Physiological snapshot at log time (for correlation — stored as scores, not raw)
    readiness_score_at_log = Column(Float, nullable=True)   # 0–100
    stress_score_at_log    = Column(Float, nullable=True)   # 0–100
    recovery_score_at_log  = Column(Float, nullable=True)   # 0–100

    # "conversation" | "manual" | "check_in"
    source = Column(String(30), nullable=False)
    notes  = Column(Text, nullable=True)

    __table_args__ = (Index("ix_mood_logs_user_date", "user_id", "log_date"),)


class AnxietyEvent(Base):
    """
    Structured anxiety/stress trigger record.

    Created when the conversation extractor identifies a specific anxiety trigger
    type, or when the user manually logs one.
    Linked to the closest StressWindow if present within ±30 minutes.
    """
    __tablename__ = "anxiety_events"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id    = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    ts         = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Trigger taxonomy
    # "deadline" | "social_pressure" | "financial" | "health_worry" |
    # "performance" | "confrontation" | "crowds" | "uncertainty" |
    # "work_overload" | "relationship" | "change" | "unknown"
    trigger_type = Column(String(40), nullable=False)
    severity     = Column(String(20), nullable=False)  # "mild"|"moderate"|"severe"

    # Physiological evidence — expressed as scores, not raw RMSSD
    stress_window_id      = Column(UUID(as_uuid=True), ForeignKey("stress_windows.id"), nullable=True)
    stress_score_at_event = Column(Float, nullable=True)   # 0–100 stress load at time of trigger
    recovery_score_drop   = Column(Float, nullable=True)   # points dropped in recovery score

    # Resolution tracking
    resolution_activity = Column(String(50), nullable=True)  # catalog slug that helped
    resolved            = Column(Boolean, nullable=True)

    # Source
    reported_via = Column(String(30), nullable=False)  # "conversation"|"manual"
    notes        = Column(Text, nullable=True)

    __table_args__ = (Index("ix_anxiety_events_user_ts", "user_id", "ts"),)


# ── Unified User Profile ───────────────────────────────────────────────────────

class UserUnifiedProfile(Base):
    """
    Persisted personality skeleton — the single durable view of the whole user.

    Rebuilt nightly by jobs/nightly_rebuild.py in two sequential LLM passes:
      Layer 1 — narrative analyst: reads all domain tables, writes coach_narrative
      Layer 2 — plan analyst: reads narrative + today's scores, writes suggested_plan_json

    The coach reads this table as its primary context lens — one DB query instead of 6.
    The prescriber reads suggested_plan_json (validated by plan_guardrails.py) instead
    of running deterministic rules.

    narrative_version increments on every rebuild so changes can be compared.
    """
    __tablename__ = "user_unified_profiles"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id    = Column(UUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    narrative_version = Column(Integer, default=1)

    # ── Layer 1 — Structured narrative (multi-section, developer + coach readable) ──
    # Full text narrative stored verbatim. Sections:
    #   PHYSIOLOGICAL TRAITS, PSYCHOLOGICAL TRAITS, BEHAVIOURAL PATTERNS,
    #   ENGAGEMENT PROFILE, CONVERSATION FACTS, COACH RELATIONSHIP,
    #   WHAT CHANGED SINCE vN, WATCH TODAY
    coach_narrative    = Column(Text, nullable=True)

    # Machine-readable fields mirrored from narrative for fast feature access
    # (these are extracted from domain tables by unified_profile_builder.py
    #  and used by plan_guardrails.py for Layer 3 validation)
    archetype_primary       = Column(String(40), nullable=True)
    archetype_secondary     = Column(String(40), nullable=True)
    training_level          = Column(Integer, nullable=True)
    days_active             = Column(Integer, default=0)

    # Physiological traits (from PersonalModel)
    prf_bpm                 = Column(Float, nullable=True)
    prf_status              = Column(String(20), nullable=True)
    coherence_trainability  = Column(String(20), nullable=True)
    recovery_arc_speed      = Column(String(20), nullable=True)   # "fast"|"normal"|"slow"
    stress_peak_pattern     = Column(String(80), nullable=True)   # human-readable e.g. "weekday 09:00"
    sleep_recovery_efficiency = Column(Float, nullable=True)

    # Psychological traits (from UserPsychProfile)
    social_energy_type      = Column(String(20), nullable=True)
    anxiety_sensitivity     = Column(Float, nullable=True)
    top_anxiety_triggers    = Column(JSON, nullable=True)         # [{type, count, strength}]
    primary_recovery_style  = Column(String(30), nullable=True)
    discipline_index        = Column(Float, nullable=True)
    streak_current          = Column(Integer, default=0)
    mood_baseline           = Column(String(20), nullable=True)
    interoception_alignment = Column(Float, nullable=True)

    # Behavioural preferences (from TagPatternModel + ActivityCoherenceEvents)
    top_calming_activities  = Column(JSON, nullable=True)         # [{slug, avg_lift, count}]
    top_stress_activities   = Column(JSON, nullable=True)         # [{slug, avg_cost, count}]
    habits_summary          = Column(JSON, nullable=True)         # from UserHabits

    # ── Engagement profile ─────────────────────────────────────────────────────
    # Band engagement
    band_days_worn_last7    = Column(Integer, nullable=True)      # 0–7
    band_days_worn_last30   = Column(Integer, nullable=True)      # 0–30
    morning_read_streak     = Column(Integer, default=0)          # consecutive morning reads
    morning_read_rate_30d   = Column(Float, nullable=True)        # 0–1
    # App engagement
    sessions_last7          = Column(Integer, default=0)
    sessions_last30         = Column(Integer, default=0)
    conversations_last7     = Column(Integer, default=0)
    nudge_response_rate_30d = Column(Float, nullable=True)        # 0–1
    last_app_interaction_days = Column(Integer, nullable=True)    # days since last any interaction
    # Engagement tier: "high"|"medium"|"low"|"at_risk"|"churned"
    engagement_tier         = Column(String(20), nullable=True)
    engagement_trend        = Column(String(20), nullable=True)   # "improving"|"stable"|"declining"

    # ── Coach relationship ─────────────────────────────────────────────────────
    preferred_tone          = Column(String(20), nullable=True)   # "compassion"|"push"|"celebrate"|"warn"
    nudge_response_rate     = Column(Float, nullable=True)        # 0–1, all-time
    best_nudge_window       = Column(String(5), nullable=True)    # "HH:MM"
    last_insight_delivered  = Column(Text, nullable=True)

    # ── Coach Watch Notes (Layer 1 nightly) ───────────────────────────────────
    # 3–5 hyper-personal insight bullets written by Layer 1 LLM.
    # JSON: list[str]  — displayed in app profile tab + injected into morning brief.
    coach_watch_notes       = Column(JSON, nullable=True)

    # ── Layer 2 — LLM-generated plan ──────────────────────────────────────────
    # Output of the nightly plan analyst LLM pass.
    # Validated by plan_guardrails.py before being committed to daily_plans.
    # Format: [{"slug", "priority", "duration_min", "reason"}]
    suggested_plan_json     = Column(JSON, nullable=True)
    plan_generated_for_date = Column(DateTime(timezone=True), nullable=True)
    plan_guardrail_notes    = Column(JSON, nullable=True)   # list of guardrail interventions
    # Layer 2 don'ts — companion to suggested_plan_json.
    # Format: [{"slug_or_label": str, "reason": str}]
    avoid_items_json        = Column(JSON, nullable=True)

    # ── Morning Brief (generated at wake-up / sleep→background transition) ────
    # LLM-derived day assessment based on 7-day trend, written at wakeup.
    # App reads these fields; no LLM call on app open.
    morning_brief_text          = Column(Text, nullable=True)
    morning_brief_day_state     = Column(String(10), nullable=True)    # "green"|"yellow"|"red"
    morning_brief_day_confidence = Column(String(10), nullable=True)   # "high"|"medium"|"low"
    morning_brief_evidence      = Column(Text, nullable=True)          # 1 sentence citing trend data
    morning_brief_one_action    = Column(Text, nullable=True)          # one specific morning action
    morning_brief_generated_for = Column(Date, nullable=True)          # IST calendar date
    morning_brief_generated_at  = Column(DateTime(timezone=True), nullable=True)

    # ── Metadata ──────────────────────────────────────────────────────────────
    data_confidence         = Column(Float, nullable=True, default=0.0)  # 0–1
    last_computed_at        = Column(DateTime(timezone=True), nullable=True)
    previous_narrative      = Column(Text, nullable=True)   # v(N-1) for delta reference

    user = relationship("User", back_populates="unified_profile")


class UserFact(Base):
    """
    Structured durable facts extracted from conversations.

    Written by profile/fact_extractor.py at conversation close.
    Surfaced in coach_narrative under CONVERSATION FACTS.
    Injected into CoachContext so the coach can reference them naturally.

    Facts have a confidence that increases with confirmation and decays with age.
    A fact at confidence < 0.3 is treated as tentative.
    A fact at confidence >= 0.7 is treated as confirmed.
    """
    __tablename__ = "user_facts"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id    = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_confirmed_at = Column(DateTime(timezone=True), nullable=True)

    # Taxonomy
    # "person"     — "has a daughter named Aria"
    # "preference" — "hates cold showers"
    # "schedule"   — "works from home Wednesdays"
    # "event"      — "big presentation Thursday"
    # "goal"       — "wants to run a 5k by June"
    # "belief"     — "doesn't think meditation works for him"
    # "health"     — "gets migraines when sleep-deprived"
    category   = Column(String(30), nullable=False)

    # Human-readable fact as extracted (max 200 chars)
    fact_text  = Column(String(200), nullable=False)

    # Structured key/value for programmatic use
    # e.g. {"entity": "daughter", "detail": "started new school"}
    fact_key   = Column(String(60), nullable=True)
    fact_value = Column(String(200), nullable=True)

    # Polarity: "positive" | "negative" | "neutral"
    polarity   = Column(String(10), nullable=False, default="neutral")

    # Confidence 0–1. Starts 0.5 on first extract. +0.2 on re-mention. Decays -0.05/week.
    confidence = Column(Float, nullable=False, default=0.5)

    # Source conversation turn id (for traceability)
    source_conversation_id = Column(UUID(as_uuid=True), nullable=True)

    # Whether the user explicitly confirmed this fact ("yes that's right", "exactly")
    user_confirmed = Column(Boolean, default=False)

    user = relationship("User", back_populates="user_facts")

    __table_args__ = (
        Index("ix_user_facts_user", "user_id"),
        Index("ix_user_facts_user_category", "user_id", "category"),
    )

# ── Tagging & Context ─────────────────────────────────────────────────────────

class ActivityCatalog(Base):
    __tablename__ = "activity_catalog"

    slug = Column(String(50), primary_key=True)
    name = Column(String(100), nullable=False)
    category = Column(String(50), nullable=False)
    intensity = Column(String(50), nullable=False)
    icon = Column(String(10), nullable=False)
    description = Column(String(200), nullable=True)

class Tag(Base):
    """Explicit mapping from a timeframe to an activity, typically linked to a Stress or Recovery Window."""
    __tablename__ = "tags"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    stress_window_id = Column(UUID(as_uuid=True), ForeignKey("stress_windows.id", ondelete="SET NULL"), nullable=True)
    recovery_window_id = Column(UUID(as_uuid=True), ForeignKey("recovery_windows.id", ondelete="SET NULL"), nullable=True)
    
    activity_slug = Column(String(50), ForeignKey("activity_catalog.slug"), nullable=False)
    
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    
    source = Column(String(50), nullable=False, default="manual")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ── Band Wear Sessions ─────────────────────────────────────────────────────────

class BandWearSession(Base):
    """
    One row per continuous band wear period.

    A session opens when the first background window arrives after either:
      - A gap > BAND_GAP_CLOSE_MINUTES (default 90) since the last window, OR
      - The very first window ever for this user.

    A session closes when:
      - A gap > BAND_GAP_CLOSE_MINUTES elapses (detected on the NEXT ingest),
        at which point is_closed=True, ended_at and final scores are written.

    Balance carry-forward:
      - On the first sleep→background context transition within this session,
        the accumulated pre-wake score (sleep recovery + prior evening stress)
        is snapshotted as opening_balance and opening_balance_locked=True.
      - Subsequent sleep→background transitions within the same session do NOT
        trigger another carry-forward (opening_balance_locked prevents it).
      - On band-off close (>90 min gap): no carry-forward. Fresh start next time.

    has_sleep_data: True if any sleep-context window exists within this session.
    """
    __tablename__ = "band_wear_sessions"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id    = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)

    started_at = Column(DateTime(timezone=True), nullable=False)   # first window start
    ended_at   = Column(DateTime(timezone=True), nullable=True)    # last window end (null while open)
    is_closed  = Column(Boolean, nullable=False, default=False)

    # Final scores (written at close)
    stress_pct    = Column(Float, nullable=True)
    recovery_pct  = Column(Float, nullable=True)
    net_balance   = Column(Float, nullable=True)
    has_sleep_data = Column(Boolean, nullable=False, default=False)

    # Carry-forward state (live, updated each ingest while open)
    opening_balance        = Column(Float, nullable=False, default=0.0)
    opening_balance_locked = Column(Boolean, nullable=False, default=False)
    # Timestamp of the first sleep→background transition within this session.
    # When set, _compute_session_summary queries only windows AFTER this point,
    # preventing the pre-wake period from being double-counted alongside opening_balance.
    wake_locked_at         = Column(DateTime(timezone=True), nullable=True)

    # Pre-computed metrics written at session close (NULL while open or no data).
    # avg_rmssd_ms / avg_hr_bpm : mean over valid background-context windows.
    # sleep_* columns            : derived from sleep-context windows in session range.
    avg_rmssd_ms       = Column(Float, nullable=True)
    avg_hr_bpm         = Column(Float, nullable=True)
    sleep_rmssd_avg_ms = Column(Float, nullable=True)
    sleep_started_at   = Column(DateTime(timezone=True), nullable=True)
    sleep_ended_at     = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_band_wear_sessions_user_started", "user_id", "started_at"),
        Index("ix_band_wear_sessions_user_open", "user_id", "is_closed"),
    )
