"""
tracking/__init__.py

Public API for the all-day tracking layer.

This module converts continuous background HRV data into the daily
Stress / Recovery / Readiness framework shown on the home screen.

Key entry points:
    process_background_window()  — called by session_service on each 5-min aggregate
    detect_stress_windows()      — run over a day's BackgroundWindows
    detect_recovery_windows()    — run over a day's BackgroundWindows
    compute_daily_summary()      — finalize DailyStressSummary at day close

Design rules:
    - Deterministic. Same input always produces same output.
    - Reads PersonalModel. Never writes to it.
    - No LLM, no AI. Threshold-based signal detection only.
    - Every function that returns a score also returns its raw inputs
      so scores are always recomputable under a different baseline.
"""

from tracking.background_processor import (
    BackgroundWindowResult,
    aggregate_background_window,
)
from tracking.stress_detector import (
    StressWindowResult,
    detect_stress_windows,
)
from tracking.recovery_detector import (
    RecoveryWindowResult,
    detect_recovery_windows,
)
from tracking.daily_summarizer import (
    DailySummaryResult,
    compute_daily_summary,
)
from tracking.wake_detector import (
    WakeSleepBoundary,
    detect_wake_sleep_boundary,
)

__all__ = [
    "BackgroundWindowResult",
    "aggregate_background_window",
    "StressWindowResult",
    "detect_stress_windows",
    "RecoveryWindowResult",
    "detect_recovery_windows",
    "DailySummaryResult",
    "compute_daily_summary",
    "WakeSleepBoundary",
    "detect_wake_sleep_boundary",
]
