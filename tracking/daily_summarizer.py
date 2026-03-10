"""
tracking/daily_summarizer.py

Computes the final DailySummaryResult from a day's stress and recovery windows.

Outputs three numbers:
    - Stress Load (0–100): how much ANS stress accumulated from wake to sleep
    - Recovery Score (0–100): how much recovery credit was deposited
    - Readiness (0–100): net position, calibrated by morning read

Formulas:

    max_possible_suppression_area =
        (personal_morning_avg - personal_floor) × waking_minutes

    actual_suppression_area =
        Σ max(0, personal_morning_avg - window_rmssd) × window_duration_min
        for each BackgroundWindow during waking hours

    stress_load = clamp(actual_suppression / max_possible × 100, 0, 100)

    ---

    Recovery uses weighted contributions from three buckets:
        sleep_area      → weight RECOVERY_WEIGHT_SLEEP
        zenflow_area    → weight RECOVERY_WEIGHT_ZENFLOW
        daytime_area    → weight RECOVERY_WEIGHT_DAYTIME

    Each bucket's area is normalized independently against the total max possible
    recovery area across all contexts, then recombined with weights.

    recovery_score = clamp(weighted_sum × 100, 0, 100)

    ---

    net_prior = recovery_score - stress_load
    readiness_prior = READINESS_CENTER + net_prior × READINESS_SCALE

    morning_calibration = morning_rmssd / personal_morning_avg
        (clamped to 0.5–1.5 to prevent extreme outliers)

    readiness = clamp(readiness_prior × morning_calibration, 0, 100)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from config import CONFIG
from tracking.background_processor import BackgroundWindowResult
from tracking.stress_detector import (
    StressWindowResult,
    compute_stress_contributions,
)
from tracking.recovery_detector import (
    RecoveryWindowResult,
    compute_recovery_contributions,
)
from tracking.wake_detector import WakeSleepBoundary


@dataclass
class DailySummaryResult:
    """
    The complete daily output: three numbers + supporting data.
    Written to the DailyStressSummary DB table.
    """
    user_id:              str
    summary_date:         datetime

    # ── Day boundary ───────────────────────────────────────────────
    wake_ts:              datetime
    sleep_ts:             Optional[datetime]
    wake_detection_method: str
    sleep_detection_method: Optional[str]
    waking_minutes:       Optional[float]

    # ── The three numbers ──────────────────────────────────────────
    stress_load_score:    Optional[float]     # 0–100, None if insufficient data
    recovery_score:       Optional[float]     # 0–100
    readiness_score:      Optional[float]     # 0–100, None until morning read arrives

    # ── Day type (for coach + UI colour) ───────────────────────────
    day_type:             Optional[str]       # "green" | "yellow" | "red"

    # ── Raw inputs (for recompute under new baseline) ──────────────
    raw_suppression_area:       float = 0.0
    raw_recovery_area_sleep:    float = 0.0
    raw_recovery_area_zenflow:  float = 0.0
    raw_recovery_area_daytime:  float = 0.0
    max_possible_suppression:   float = 0.0
    capacity_floor_used:        Optional[float] = None
    capacity_version:           int = 0

    # ── Calibration metadata ───────────────────────────────────────
    calibration_days:     int = 0               # how many baseline days were available
    is_estimated:         bool = True           # True if calibration_days < FULL_ACCURACY_DAYS
    is_partial_data:      bool = False          # True if >2h gap in background stream

    # ── Top contributors (FK stubs — filled by DB layer) ──────────
    top_stress_window_id:    Optional[str] = None
    top_recovery_window_id:  Optional[str] = None


def compute_daily_summary(
    user_id: str,
    summary_date: datetime,
    background_windows: list[BackgroundWindowResult],
    stress_windows: list[StressWindowResult],
    recovery_windows: list[RecoveryWindowResult],
    boundary: WakeSleepBoundary,
    personal_morning_avg: float,
    personal_floor: float,
    personal_ceiling: float,
    capacity_version: int,
    calibration_days: int,
    morning_rmssd: Optional[float] = None,     # None → readiness not yet computable
    capacity_floor_used: Optional[float] = None,
) -> DailySummaryResult:
    """
    Compute the full daily summary.

    Parameters
    ----------
    user_id, summary_date
        Identity.
    background_windows
        All BackgroundWindowResult rows for this day (both valid and invalid included —
        we use invalid ones only for gap detection).
    stress_windows
        Output of detect_stress_windows for this day.
    recovery_windows
        Output of detect_recovery_windows for this day.
    boundary
        WakeSleepBoundary for this day.
    personal_morning_avg : float
        PersonalModel.rmssd_morning_avg — normalization reference.
    personal_floor : float
        PersonalModel.rmssd_floor — lower bound for capacity formula.
    personal_ceiling : float
        PersonalModel.rmssd_ceiling — upper bound for recovery capacity formula.
    capacity_version : int
        PersonalModel.capacity_version at time of computation.
    calibration_days : int
        How many days of real personal baseline data exist.
    morning_rmssd : float, optional
        Today's morning read RMSSD. If None, readiness_score stays None.
    capacity_floor_used : float, optional
        If personalModel has stress_capacity_floor_rmssd, pass it here.
        Defaults to personal_floor if None.
    """
    cfg = CONFIG.tracking
    cap_floor = capacity_floor_used if capacity_floor_used is not None else personal_floor
    waking_minutes = boundary.waking_minutes or 0.0

    # ── Gap analysis ────────────────────────────────────────────────────────
    is_partial = _check_partial_data(background_windows, cfg.GAP_PARTIAL_DATA_MINUTES)

    # ── Stress Load ─────────────────────────────────────────────────────────
    # Max possible: (avg - floor) × waking_minutes
    max_possible_suppression = max(
        0.0,
        (personal_morning_avg - cap_floor) * waking_minutes
    )

    # Actual suppression area from all background windows in waking hours
    actual_suppression = _compute_suppression_area(
        windows=background_windows,
        personal_morning_avg=personal_morning_avg,
        wake_ts=boundary.wake_ts,
        sleep_ts=boundary.sleep_ts,
        window_duration=cfg.BACKGROUND_WINDOW_MINUTES,
    )

    stress_load: Optional[float] = None
    if max_possible_suppression > 0 and waking_minutes > 0:
        stress_load = round(
            _clamp(actual_suppression / max_possible_suppression * 100.0, 0.0, 100.0),
            1
        )

    # Fill stress window contributions
    compute_stress_contributions(stress_windows, max_possible_suppression)

    # ── Recovery Score ───────────────────────────────────────────────────────
    # Max possible recovery area (ceiling - avg) × total recovery window time
    # We use the same max possible suppression denominator for symmetry
    # (floor ↔ ceiling inverted)
    max_possible_recovery = max(
        0.0,
        (personal_ceiling - personal_morning_avg) * (waking_minutes + 480.0)
        # +480 min (~8h) for sleep — recovery window is longer than stress window
    )

    raw_sleep = sum(
        rw.recovery_area for rw in recovery_windows if rw.context == "sleep"
    )
    raw_zenflow = sum(
        rw.recovery_area
        for rw in recovery_windows
        if rw.tag == "zenflow_session"
    )
    raw_daytime = sum(
        rw.recovery_area
        for rw in recovery_windows
        if rw.context == "background" and rw.tag != "zenflow_session"
    )

    compute_recovery_contributions(recovery_windows, max_possible_recovery)

    recovery_score: Optional[float] = None
    if max_possible_recovery > 0:
        # Weighted combination
        sleep_frac = raw_sleep / max_possible_recovery
        zenflow_frac = raw_zenflow / max_possible_recovery
        daytime_frac = raw_daytime / max_possible_recovery

        weighted = (
            sleep_frac * cfg.RECOVERY_WEIGHT_SLEEP
            + zenflow_frac * cfg.RECOVERY_WEIGHT_ZENFLOW
            + daytime_frac * cfg.RECOVERY_WEIGHT_DAYTIME
        )
        # Scale back to 0–100: weighted is a fraction of the max, re-normalize
        # so that getting 100% of sleep credit alone produces ~50 (not 100)
        # Full credit across all three buckets → 100
        max_frac = (
            cfg.RECOVERY_WEIGHT_SLEEP
            + cfg.RECOVERY_WEIGHT_ZENFLOW
            + cfg.RECOVERY_WEIGHT_DAYTIME
        )
        # Normalize actual fractions against max possible (which could exceed 1 for
        # high-RMSSD nights — cap at 1.0 per bucket)
        sleep_norm = _clamp(sleep_frac / cfg.RECOVERY_WEIGHT_SLEEP, 0.0, 1.0) if cfg.RECOVERY_WEIGHT_SLEEP > 0 else 0.0
        zenflow_norm = _clamp(zenflow_frac / cfg.RECOVERY_WEIGHT_ZENFLOW, 0.0, 1.0) if cfg.RECOVERY_WEIGHT_ZENFLOW > 0 else 0.0
        daytime_norm = _clamp(daytime_frac / cfg.RECOVERY_WEIGHT_DAYTIME, 0.0, 1.0) if cfg.RECOVERY_WEIGHT_DAYTIME > 0 else 0.0

        recovery_weighted = (
            sleep_norm * cfg.RECOVERY_WEIGHT_SLEEP
            + zenflow_norm * cfg.RECOVERY_WEIGHT_ZENFLOW
            + daytime_norm * cfg.RECOVERY_WEIGHT_DAYTIME
        )
        recovery_score = round(_clamp(recovery_weighted * 100.0, 0.0, 100.0), 1)

    # ── Readiness ────────────────────────────────────────────────────────────
    readiness_score: Optional[float] = None
    if morning_rmssd is not None and stress_load is not None and recovery_score is not None:
        net_prior = recovery_score - stress_load
        readiness_prior = cfg.READINESS_CENTER + net_prior * cfg.READINESS_SCALE
        morning_calibration = _clamp(
            morning_rmssd / personal_morning_avg, 0.5, 1.5
        )
        readiness_score = round(
            _clamp(readiness_prior * morning_calibration, 0.0, 100.0), 1
        )

    # ── Day type ─────────────────────────────────────────────────────────────
    day_type: Optional[str] = None
    if readiness_score is not None:
        if readiness_score >= cfg.READINESS_GREEN_THRESHOLD:
            day_type = "green"
        elif readiness_score >= cfg.READINESS_YELLOW_THRESHOLD:
            day_type = "yellow"
        else:
            day_type = "red"

    # ── Top contributors ─────────────────────────────────────────────────────
    top_stress: Optional[StressWindowResult] = None
    if stress_windows:
        top_stress = max(stress_windows, key=lambda s: s.suppression_area)

    top_recovery: Optional[RecoveryWindowResult] = None
    if recovery_windows:
        top_recovery = max(recovery_windows, key=lambda r: r.recovery_area)

    is_estimated = calibration_days < cfg.CAPACITY_FULL_ACCURACY_DAYS

    return DailySummaryResult(
        user_id=user_id,
        summary_date=summary_date,
        wake_ts=boundary.wake_ts,
        sleep_ts=boundary.sleep_ts,
        wake_detection_method=boundary.wake_detection_method,
        sleep_detection_method=boundary.sleep_detection_method,
        waking_minutes=waking_minutes,
        stress_load_score=stress_load,
        recovery_score=recovery_score,
        readiness_score=readiness_score,
        day_type=day_type,
        raw_suppression_area=round(actual_suppression, 2),
        raw_recovery_area_sleep=round(raw_sleep, 2),
        raw_recovery_area_zenflow=round(raw_zenflow, 2),
        raw_recovery_area_daytime=round(raw_daytime, 2),
        max_possible_suppression=round(max_possible_suppression, 2),
        capacity_floor_used=cap_floor,
        capacity_version=capacity_version,
        calibration_days=calibration_days,
        is_estimated=is_estimated,
        is_partial_data=is_partial,
        top_stress_window_id=None,   # DB layer fills FK
        top_recovery_window_id=None,
    )


def _compute_suppression_area(
    windows: list[BackgroundWindowResult],
    personal_morning_avg: float,
    wake_ts: Optional[datetime],
    sleep_ts: Optional[datetime],
    window_duration: int,
) -> float:
    """Sum of max(0, avg - rmssd) × duration for valid background windows in waking hours."""
    total = 0.0
    for w in windows:
        if not w.is_valid or w.context != "background" or w.rmssd_ms is None:
            continue
        if wake_ts is not None and w.window_start < wake_ts:
            continue
        if sleep_ts is not None and w.window_end > sleep_ts:
            continue
        total += max(0.0, personal_morning_avg - w.rmssd_ms) * window_duration
    return total


def _check_partial_data(
    windows: list[BackgroundWindowResult],
    gap_threshold_minutes: int,
) -> bool:
    """Return True if any gap between consecutive background windows exceeds the threshold."""
    bg = sorted(
        [w for w in windows if w.context == "background"],
        key=lambda w: w.window_start,
    )
    for i in range(1, len(bg)):
        gap = (bg[i].window_start - bg[i - 1].window_end).total_seconds() / 60.0
        if gap > gap_threshold_minutes:
            return True
    return False


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
