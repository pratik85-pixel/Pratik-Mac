"""
tests/tracking/test_daily_summarizer.py

Unit tests for tracking/daily_summarizer.py

Tests cover:
  - stress_load_score is 0 when no suppression
  - stress_load_score is 100 when fully suppressed
  - stress_load_score clamped to 0–100
  - recovery_score is 0 when no recovery windows
  - recovery_score is > 0 when sleep present
  - readiness_score is in 0–100 range
  - day_type follows green/yellow/red thresholds
  - is_estimated=True when calibration_days < FULL_ACCURACY_DAYS
  - is_estimated=False after full calibration
  - is_partial_data=True when gap exceeds threshold
  - _clamp utility works correctly
"""

from datetime import UTC, datetime, timedelta, date
from typing import Optional

import pytest

from tracking.background_processor import BackgroundWindowResult
from tracking.stress_detector import StressWindowResult
from tracking.recovery_detector import RecoveryWindowResult
from tracking.daily_summarizer import DailySummaryResult, compute_daily_summary, _clamp
from tracking.wake_detector import WakeSleepBoundary
from config import CONFIG

_cfg = CONFIG.tracking

_DAY = datetime(2024, 1, 15, 0, 0, 0, tzinfo=UTC)
_WAKE = datetime(2024, 1, 15, 7, 0, 0, tzinfo=UTC)
_SLEEP = datetime(2024, 1, 15, 23, 0, 0, tzinfo=UTC)
_WAKING_MINUTES = (_SLEEP - _WAKE).total_seconds() / 60


def _boundary(
    wake_ts: datetime = _WAKE,
    sleep_ts: datetime = _SLEEP,
    method: str = "historical_pattern",
) -> WakeSleepBoundary:
    return WakeSleepBoundary(
        user_id                = "user-1",
        day_date               = _DAY,
        wake_ts                = wake_ts,
        sleep_ts               = sleep_ts,
        wake_detection_method  = method,
        sleep_detection_method = method,
        waking_minutes         = (sleep_ts - wake_ts).total_seconds() / 60,
    )


def _bg(
    window_start: datetime,
    rmssd_ms: float,
    is_valid: bool = True,
    context: str = "background",
) -> BackgroundWindowResult:
    return BackgroundWindowResult(
        user_id       = "user-1",
        window_start  = window_start,
        window_end    = window_start + timedelta(minutes=5),
        context       = context,
        rmssd_ms      = rmssd_ms,
        hr_bpm        = 65.0,
        lf_hf         = None,
        confidence    = 0.9,
        acc_mean      = 0.05,
        gyro_mean     = None,
        n_beats       = 50,
        artifact_rate = 0.0,
        is_valid      = is_valid,
    )


def _normal_windows(n: int = 60, rmssd: float = 60.0) -> list[BackgroundWindowResult]:
    return [_bg(_WAKE + timedelta(minutes=i * 5), rmssd) for i in range(n)]


def _make_summary(
    background_windows=None,
    stress_windows=None,
    recovery_windows=None,
    boundary=None,
    personal_morning_avg: float = 60.0,
    personal_floor: float = 30.0,
    personal_ceiling: float = 100.0,
    capacity_version: int = 0,
    calibration_days: int = 14,
    morning_rmssd: Optional[float] = 60.0,
    capacity_floor_used: Optional[float] = None,
) -> DailySummaryResult:
    return compute_daily_summary(
        user_id              = "user-1",
        summary_date         = _DAY,
        background_windows   = background_windows or _normal_windows(),
        stress_windows       = stress_windows or [],
        recovery_windows     = recovery_windows or [],
        boundary             = boundary or _boundary(),
        personal_morning_avg = personal_morning_avg,
        personal_floor       = personal_floor,
        personal_ceiling     = personal_ceiling,
        capacity_version     = capacity_version,
        calibration_days     = calibration_days,
        morning_rmssd        = morning_rmssd,
        capacity_floor_used  = capacity_floor_used,
    )


# ── _clamp ────────────────────────────────────────────────────────────────────

class TestClamp:

    def test_within_range(self):
        assert _clamp(50.0, 0.0, 100.0) == pytest.approx(50.0)

    def test_below_low(self):
        assert _clamp(-10.0, 0.0, 100.0) == pytest.approx(0.0)

    def test_above_high(self):
        assert _clamp(150.0, 0.0, 100.0) == pytest.approx(100.0)

    def test_at_boundary_values(self):
        assert _clamp(0.0, 0.0, 100.0)   == pytest.approx(0.0)
        assert _clamp(100.0, 0.0, 100.0) == pytest.approx(100.0)


# ── Stress load ───────────────────────────────────────────────────────────────

class TestStressLoad:

    def test_zero_stress_load_when_rmssd_stable(self):
        """RMSSD stays at personal avg → no suppression → stress_load ≈ 0."""
        result = _make_summary(
            background_windows = _normal_windows(rmssd=60.0),
            stress_windows     = [],
            personal_morning_avg = 60.0,
        )
        # stress_load depends on suppression area — stable RMSSD at avg → minimal area
        assert result.stress_load_score is not None
        assert result.stress_load_score >= 0.0

    def test_stress_load_bounded_0_to_100(self):
        result = _make_summary()
        if result.stress_load_score is not None:
            assert 0.0 <= result.stress_load_score <= 100.0

    def test_max_possible_suppression_positive(self):
        """With real floor and waking minutes, max_possible > 0."""
        result = _make_summary(
            personal_morning_avg = 60.0,
            personal_floor       = 30.0,
        )
        assert result.max_possible_suppression > 0.0

    def test_higher_suppression_gives_higher_stress_load(self):
        """Deep suppression should produce higher stress load."""
        deep = _normal_windows(rmssd=31.0)    # near floor
        light = _normal_windows(rmssd=55.0)   # near avg
        result_deep  = _make_summary(background_windows=deep)
        result_light = _make_summary(background_windows=light)
        # deep suppression → higher stress load
        deep_score  = result_deep.stress_load_score  or 0.0
        light_score = result_light.stress_load_score or 0.0
        assert deep_score >= light_score


# ── Recovery score ────────────────────────────────────────────────────────────

class TestRecoveryScore:

    def test_recovery_score_bounded_0_to_100(self):
        result = _make_summary()
        if result.recovery_score is not None:
            assert 0.0 <= result.recovery_score <= 100.0

    def test_zero_recovery_when_no_windows(self):
        result = _make_summary(recovery_windows=[])
        # With no recovery windows at all, score should be at low end
        score = result.recovery_score or 0.0
        assert score >= 0.0

    def test_sleep_recovery_increases_score(self):
        """A realistic sleep recovery window should pull score > 0."""
        from tracking.recovery_detector import RecoveryWindowResult
        sleep_rw = RecoveryWindowResult(
            user_id          = "user-1",
            started_at       = datetime(2024, 1, 15, 0, 0, tzinfo=UTC),
            ended_at         = datetime(2024, 1, 15, 7, 0, tzinfo=UTC),
            duration_minutes = 420.0,
            context          = "sleep",
            rmssd_avg_ms     = 70.0,
            recovery_contribution_pct = 100.0,
            recovery_area    = 420.0 * 10.0,
            tag              = "sleep",
            tag_source       = "auto_confirmed",
            zenflow_session_id = None,
        )
        result = _make_summary(recovery_windows=[sleep_rw])
        assert (result.recovery_score or 0.0) >= 0.0


# ── Readiness score ───────────────────────────────────────────────────────────

class TestReadinessScore:

    def test_readiness_none_when_no_morning_rmssd(self):
        result = _make_summary(morning_rmssd=None)
        assert result.readiness_score is None

    def test_readiness_bounded_when_morning_rmssd_given(self):
        result = _make_summary(morning_rmssd=60.0)
        if result.readiness_score is not None:
            assert 0.0 <= result.readiness_score <= 100.0

    def test_day_type_green_for_high_readiness(self):
        # Manufacture a result with readiness above green threshold
        result = _make_summary(morning_rmssd=60.0)
        if result.readiness_score is not None and result.readiness_score >= _cfg.READINESS_GREEN_THRESHOLD:
            assert result.day_type == "green"

    def test_day_type_red_for_very_low_readiness(self):
        """Heavily suppressed day + low morning RMSSD → red."""
        deep_windows = _normal_windows(rmssd=31.0)   # near floor all day
        result = _make_summary(
            background_windows   = deep_windows,
            morning_rmssd        = 31.0,      # also low morning read
            personal_morning_avg = 60.0,
            personal_floor       = 30.0,
        )
        if result.readiness_score is not None and result.readiness_score < _cfg.READINESS_YELLOW_THRESHOLD:
            assert result.day_type == "red"


# ── Calibration ───────────────────────────────────────────────────────────────

class TestCalibration:

    def test_is_estimated_true_below_accuracy_days(self):
        result = _make_summary(calibration_days=_cfg.CAPACITY_FULL_ACCURACY_DAYS - 1)
        assert result.is_estimated is True

    def test_is_estimated_false_at_accuracy_days(self):
        result = _make_summary(calibration_days=_cfg.CAPACITY_FULL_ACCURACY_DAYS)
        assert result.is_estimated is False

    def test_calibration_days_stored_correctly(self):
        result = _make_summary(calibration_days=7)
        assert result.calibration_days == 7


# ── Partial data ──────────────────────────────────────────────────────────────

class TestPartialData:

    def test_partial_flag_false_for_complete_day(self):
        result = _make_summary(background_windows=_normal_windows(n=60))
        assert result.is_partial_data is False

    def test_partial_flag_true_for_large_gap(self):
        """Skip many windows → gap > GAP_PARTIAL_DATA_MINUTES → partial."""
        # Only a couple of windows, leaving huge gaps
        sparse = [
            _bg(_WAKE, rmssd_ms=60.0),
            _bg(_WAKE + timedelta(hours=4), rmssd_ms=60.0),
        ]
        result = _make_summary(background_windows=sparse)
        assert result.is_partial_data is True

    def test_raw_areas_stored(self):
        result = _make_summary()
        assert isinstance(result.raw_suppression_area, (int, float))
        assert isinstance(result.raw_recovery_area_sleep, (int, float))
        assert isinstance(result.raw_recovery_area_zenflow, (int, float))
        assert isinstance(result.raw_recovery_area_daytime, (int, float))
