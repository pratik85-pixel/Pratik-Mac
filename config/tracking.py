"""
config/tracking.py

Configuration for the all-day tracking layer (tracking/).

Covers:
  - BackgroundWindow granularity
  - Stress event detection thresholds
  - Recovery event detection thresholds
  - Recovery score weighting
  - Readiness formula parameters
  - Adaptive capacity baseline update rules
  - Nudge cap and override rules
  - Gap handling
  - Motion thresholds
  - Auto-tag pattern learning minimums

downstream: tracking/background_processor, tracking/stress_detector,
            tracking/recovery_detector, tracking/daily_summarizer,
            tracking/wake_detector, api/services/tracking_service
"""

from __future__ import annotations

from pydantic_settings import BaseSettings


class TrackingConfig(BaseSettings):

    # ── Background Window ───────────────────────────────────────────────────
    # downstream: tracking/background_processor (window granularity in minutes)
    BACKGROUND_WINDOW_MINUTES: int = 5

    # downstream: tracking/background_processor (min beats for valid RMSSD)
    BACKGROUND_MIN_BEATS: int = 25

    # Population-level ceiling for RMSSD validity gate.
    # Windows above this threshold are optical-PPG motion artefacts, not genuine HRV.
    # downstream: tracking/background_processor (is_valid), tracking/daily_summarizer (area clamp)
    RMSSD_POPULATION_CEILING: float = 110.0

    # Population-level floor for RMSSD validity gate.
    # Windows below this are dead-signal contact loss — no living NS produces <3 ms RMSSD.
    # Only applied to context="background" windows (mirrors ceiling gate symmetrically).
    # downstream: tracking/background_processor (is_valid), tracking/daily_summarizer (area clamp)
    RMSSD_POPULATION_FLOOR: float = 3.0

    # ── Stress Detection ────────────────────────────────────────────────────
    # downstream: tracking/stress_detector
    # RMSSD must fall below this fraction of personal morning average to breach threshold
    STRESS_THRESHOLD_PCT: float = 0.75

    # Minimum consecutive windows at threshold to declare a stress event (5 min each → 15 min)
    STRESS_MIN_WINDOWS: int = 3

    # Adjacent events with gap ≤ this (minutes) are merged into one event
    STRESS_MERGE_GAP_MINUTES: int = 5

    # Rate-of-change trigger: RMSSD dropped > this fraction in a single window
    STRESS_RATE_TRIGGER_PCT: float = 0.20

    # Minimum contribution fraction of daily capacity to warrant a nudge
    STRESS_MIN_NUDGE_CONTRIBUTION: float = 0.03

    # ── Recovery Detection ─────────────────────────────────────────────────
    # downstream: tracking/recovery_detector
    # RMSSD must be at or above this fraction of personal morning average
    RECOVERY_THRESHOLD_PCT: float = 1.10

    # Minimum consecutive windows above threshold to declare a recovery window
    RECOVERY_MIN_WINDOWS: int = 4


    # ── Credit-Card Scoring Model ──────────────────────────────────────────
    # downstream: tracking/daily_summarizer
    # Fixed denominator for both Stress Load and Waking Recovery Score.
    # Represents a full 16-hour waking day in minutes.
    # Using a fixed denominator ensures:
    #   - score never drifts DOWN just because time passes (old bug)
    #   - early-morning events are honest (small % of full-day budget)
    #   - users can directly compare across time-of-day
    DAILY_CAPACITY_WAKING_MINUTES: int = 960    # 16 h × 60 min — stress budget (waking only)
    DAILY_CAPACITY_RECOVERY_MINUTES: int = 1440  # 24 h × 60 min — recovery budget (full day)

    # ── Day Type Thresholds (MorningRead → green/yellow/red) ───────────────────
    # downstream: api/services/tracking_service (morning read ingest)
    # vs_personal_avg_pct thresholds for day_type classification on MorningRead.
    # These live in tracking_service._classify_morning_day_type().
    # Net balance drives plan guardrails — see profile/plan_guardrails.py.

    # ── Adaptive Capacity Baseline ─────────────────────────────────────────
    # downstream: tracking/daily_summarizer, model/personal_distributions
    # Floor shift must exceed this fraction to trigger potential update
    CAPACITY_UPDATE_FLOOR_SHIFT_PCT: float = 0.10

    # Floor shift must sustain for this many consecutive days before updating
    CAPACITY_UPDATE_MIN_SUSTAINED_DAYS: int = 7

    # downstream: tracking/background_processor
    # Gaps shorter than this (minutes) are treated as continuous
    GAP_CONTINUITY_MINUTES: int = 30

    # Gaps longer than this (minutes) mark the day as partial data
    GAP_PARTIAL_DATA_MINUTES: int = 120

    # Gap threshold (minutes) used to detect band removal and close a BandWearSession.
    # When no background window arrives for this long, the session is considered ended.
    BAND_GAP_CLOSE_MINUTES: int = 90

    # ── Motion Thresholds ──────────────────────────────────────────────────
    # downstream: tracking/stress_detector (physical vs emotional classification)
    # ACC mean magnitude above this → movement detected → physical_load_candidate
    MOTION_ACTIVE_THRESHOLD: float = 0.30

    # ── Wake / Sleep Boundary ──────────────────────────────────────────────
    # downstream: tracking/wake_detector
    # After a background gap longer than this (hours), assume sleep started
    SLEEP_GAP_HOURS: float = 3.0

    # Rolling window for computing typical_wake_time / typical_sleep_time
    WAKE_HISTORY_DAYS: int = 14

    # ── Auto-Tag Pattern Learning ──────────────────────────────────────────
    # downstream: tracking/auto_tagger (Phase 2)
    # Need at least this many confirmed matching events before auto-tagging
    AUTOTAG_MIN_CONFIRMED_EVENTS: int = 4

    # Auto-tagging only activates after this many days of wear data
    AUTOTAG_MIN_DAYS: int = 28

    # ── Morning Read ──────────────────────────────────────────────────────
    # downstream: api/services/tracking_service
    # Exponential weight for EWM update of rmssd_morning_avg from morning reads.
    # α=0.2 means each new reading has 20% weight; accumulated history has 80%.
    # Active pre-calibration-lock only.
    MORNING_EWM_ALPHA: float = 0.2

    class Config:
        env_prefix = "TRACKING_"
        case_sensitive = False
