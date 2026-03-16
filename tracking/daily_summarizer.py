"""
tracking/daily_summarizer.py

Computes the final DailySummaryResult from a day's stress and recovery windows.

Outputs three numbers + a running balance:
    - Stress Load (0–100 display): how much ANS stress accumulated from wake to sleep
    - Waking Recovery Score (0–100 display): how much recovery credit was deposited
    - Net Balance (unbounded): credit-card statement including opening carry-forward

Formulas ("Credit Card" model):

    SINGLE SYMMETRIC DENOMINATOR:

        ns_capacity = (personal_ceiling - personal_floor)
                      × DAILY_CAPACITY_WAKING_MINUTES (960 min)

        This is the credit limit. Both stress and recovery are measured
        against the same denominator — personal HRV range × full day.
        personal_floor and personal_ceiling are FROZEN at calibration snapshot,
        not updated daily via EWM.

    STRESS % (raw, uncapped):

        actual_suppression_area =
            Σ max(0, personal_morning_avg - window_rmssd) × window_duration_min
            for each waking BackgroundWindow

        stress_pct_raw = actual_suppression_area / ns_capacity × 100
        (can exceed 100 on severe days — represents genuine debt)

    RECOVERY % (raw, uncapped):

        actual_recovery_area_waking =
            Σ max(0, window_rmssd - personal_morning_avg) × window_duration_min
            for each waking BackgroundWindow

        recovery_pct_raw = actual_recovery_area_waking / ns_capacity × 100

    NET BALANCE — single continuous thread, never resets:

        net_balance = recovery_pct_raw - stress_pct_raw + opening_balance
        opening_balance = previous day's closing_balance (or 0 on first day)
        closing_balance = net_balance at end of day

    DISPLAY SCORES (clamped for UI only — do not feed net_balance from these):

        stress_load_score       = clamp(stress_pct_raw, 0, 100)
        waking_recovery_score   = clamp(recovery_pct_raw, 0, 100)

    DAY TYPE (green/yellow/red) — sourced from MorningRead.day_type at day close.
    Passed in as a parameter; not computed here.
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

    # ── Day type (for coach + UI colour) ───────────────────────────
    # Sourced from MorningRead.day_type — NOT computed here.
    day_type:             Optional[str]       # "green" | "yellow" | "red"

    # ── Raw inputs (for recompute under new baseline) ──────────────
    raw_suppression_area:         float = 0.0
    raw_recovery_area_sleep:      float = 0.0
    raw_recovery_area_zenflow:    float = 0.0
    raw_recovery_area_daytime:    float = 0.0
    raw_recovery_area_waking:     float = 0.0   # RMSSD-above-baseline during waking hours
    # ns_capacity_used = (ceiling - floor) × 960 — single frozen denominator
    ns_capacity_used:             float = 0.0
    # legacy field — kept for DB backward compat, now equals ns_capacity_used
    max_possible_suppression:     float = 0.0
    capacity_floor_used:          Optional[float] = None
    capacity_version:             int = 0

    # ── Credit-card scores ─────────────────────────────────────────
    waking_recovery_score:        Optional[float] = None   # display only, clamped 0–100
    net_balance:                  Optional[float] = None   # raw: recovery% - stress% + opening_balance

    # ── Continuous balance thread ──────────────────────────────────
    opening_balance:              float = 0.0              # carried in from previous day close (= recovery + stress)
    opening_recovery:             float = 0.0              # positive component: max(0, opening_balance) — prior surplus
    opening_stress:               float = 0.0              # negative component: min(0, opening_balance) — prior debt (≤0)
    closing_balance:              Optional[float] = None   # = net_balance at end of day

    # ── Raw unclamped percentages (for carry-forward integrity) ────
    stress_pct_raw:               Optional[float] = None   # stress_area / ns_capacity × 100 (unbounded)
    recovery_pct_raw:             Optional[float] = None   # recovery_area / ns_capacity × 100 (unbounded)

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
    calibration_locked: bool = False,          # True once calibration_locked_at is set
    day_type: Optional[str] = None,            # from MorningRead.day_type at day close
    capacity_floor_used: Optional[float] = None,
    opening_balance: float = 0.0,              # carry-forward from previous closing_balance
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
    calibration_locked : bool
        True once calibration_locked_at is set (Day 3). Clears is_estimated flag.
    day_type : str | None
        "green"|"yellow"|"red" from today's MorningRead row. None if no read yet.
    capacity_floor_used : float, optional
        If personalModel has stress_capacity_floor_rmssd, pass it here.
        Defaults to personal_floor if None.
    opening_balance : float, optional
        Previous day's closing_balance. Carries the debt or surplus forward.
        0.0 on first day or when no history exists.
    """
    cfg = CONFIG.tracking
    cap_floor = capacity_floor_used if capacity_floor_used is not None else personal_floor
    waking_minutes = boundary.waking_minutes or 0.0

    # ── Gap analysis ────────────────────────────────────────────────────────
    is_partial = _check_partial_data(background_windows, cfg.GAP_PARTIAL_DATA_MINUTES)

    # ── Single symmetric denominator: (ceiling - floor) × 960 ───────────────
    # Both stress and recovery are measured against the same capacity.
    # personal_floor and personal_ceiling MUST be frozen calibration snapshots —
    # do not pass live EWM-updated values here.
    ns_capacity = max(
        0.0,
        (personal_ceiling - personal_floor) * cfg.DAILY_CAPACITY_WAKING_MINUTES
    )
    # Keep legacy field populated for backward compat
    max_possible_suppression = ns_capacity

    # ── Actual stress area (suppression below morning baseline) ─────────────
    actual_suppression = _compute_suppression_area(
        windows=background_windows,
        personal_morning_avg=personal_morning_avg,
        wake_ts=boundary.wake_ts,
        sleep_ts=boundary.sleep_ts,
        window_duration=cfg.BACKGROUND_WINDOW_MINUTES,
    )

    # ── Actual waking recovery area (RMSSD above morning baseline) ──────────
    actual_recovery_area_waking = _compute_recovery_area_waking(
        windows=background_windows,
        personal_morning_avg=personal_morning_avg,
        wake_ts=boundary.wake_ts,
        sleep_ts=boundary.sleep_ts,
        window_duration=cfg.BACKGROUND_WINDOW_MINUTES,
    )

    # ── Raw percentages (unbounded — do NOT clamp before net_balance) ────────
    stress_pct_raw: Optional[float] = None
    recovery_pct_raw: Optional[float] = None
    if ns_capacity > 0 and waking_minutes > 0:
        stress_pct_raw   = round(actual_suppression / ns_capacity * 100.0, 2)
        recovery_pct_raw = round(actual_recovery_area_waking / ns_capacity * 100.0, 2)

    # ── Display scores (clamped 0–100 for UI rendering only) ─────────────────
    stress_load: Optional[float] = None
    waking_recovery_score: Optional[float] = None
    if stress_pct_raw is not None:
        stress_load           = round(_clamp(stress_pct_raw, 0.0, 100.0), 1)
        waking_recovery_score = round(_clamp(recovery_pct_raw or 0.0, 0.0, 100.0), 1)

    # Fill stress window contributions (uses ns_capacity for % calc)
    compute_stress_contributions(stress_windows, ns_capacity)

    # ── Recovery areas stored for raw-area audit trail ──────────────────────
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

    compute_recovery_contributions(recovery_windows, ns_capacity)

    # ── Net Balance — computed from RAW unclamped %s + opening carry-forward ─
    # NEVER compute net_balance from clamped display scores: that loses information
    # when stress exceeds 100 ("deep debt" days).
    net_balance: Optional[float] = None
    closing_balance: Optional[float] = None
    opening_recovery = max(0.0, opening_balance)   # positive: prior surplus
    opening_stress   = min(0.0, opening_balance)   # negative: prior debt
    if stress_pct_raw is not None and recovery_pct_raw is not None:
        net_balance     = round(recovery_pct_raw - stress_pct_raw + opening_balance, 1)
        closing_balance = net_balance

    # ── Top contributors ─────────────────────────────────────────────────────
    top_stress: Optional[StressWindowResult] = None
    if stress_windows:
        top_stress = max(stress_windows, key=lambda s: s.suppression_area)

    top_recovery: Optional[RecoveryWindowResult] = None
    if recovery_windows:
        top_recovery = max(recovery_windows, key=lambda r: r.recovery_area)

    # is_estimated clears once calibration is locked (Day 3), not at Day 14
    is_estimated = not calibration_locked

    return DailySummaryResult(
        user_id=user_id,
        summary_date=summary_date,
        wake_ts=boundary.wake_ts,
        sleep_ts=boundary.sleep_ts,
        wake_detection_method=boundary.wake_detection_method,
        sleep_detection_method=boundary.sleep_detection_method,
        waking_minutes=waking_minutes,
        stress_load_score=stress_load,
        day_type=day_type,
        raw_suppression_area=round(actual_suppression, 2),
        raw_recovery_area_sleep=round(raw_sleep, 2),
        raw_recovery_area_zenflow=round(raw_zenflow, 2),
        raw_recovery_area_daytime=round(raw_daytime, 2),
        raw_recovery_area_waking=round(actual_recovery_area_waking, 2),
        ns_capacity_used=round(ns_capacity, 2),
        max_possible_suppression=round(ns_capacity, 2),  # legacy compat
        capacity_floor_used=cap_floor,
        capacity_version=capacity_version,
        waking_recovery_score=waking_recovery_score,
        net_balance=net_balance,
        opening_balance=opening_balance,
        opening_recovery=opening_recovery,
        opening_stress=opening_stress,
        closing_balance=closing_balance,
        stress_pct_raw=stress_pct_raw,
        recovery_pct_raw=recovery_pct_raw,
        calibration_days=calibration_days,
        is_estimated=is_estimated,
        is_partial_data=is_partial,
        top_stress_window_id=None,   # DB layer fills FK
        top_recovery_window_id=None,
    )


def _compute_recovery_area_waking(
    windows: list[BackgroundWindowResult],
    personal_morning_avg: float,
    wake_ts: Optional[datetime],
    sleep_ts: Optional[datetime],
    window_duration: int,
) -> float:
    """Sum of max(0, rmssd - avg) × duration for valid waking windows.

    This is the symmetric credit leg of the credit-card model:
    windows where RMSSD is *above* morning baseline accumulate recovery credit.
    Like stress_balance, this only ever increases — a true ratchet.
    """
    total = 0.0
    for w in windows:
        if not w.is_valid or w.context != "background" or w.rmssd_ms is None:
            continue
        if wake_ts is not None and w.window_start < wake_ts:
            continue
        if sleep_ts is not None and w.window_end > sleep_ts:
            continue
        total += max(0.0, w.rmssd_ms - personal_morning_avg) * window_duration
    return total


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
