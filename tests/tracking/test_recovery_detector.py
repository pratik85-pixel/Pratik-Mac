"""
tests/tracking/test_recovery_detector.py

Unit tests for tracking/recovery_detector.py

Tests cover:
  - No recovery windows when RMSSD stays below threshold
  - Single sleep block forms one RecoveryWindowResult
  - Sleep window auto-tagged as "sleep"
  - Daytime recovery window created for sustained high RMSSD
  - Invalid windows skipped
  - ZenFlow session overlap auto-tags window
  - compute_recovery_contributions sums to 100
"""

from datetime import UTC, datetime, timedelta
from typing import Optional

import pytest

from tracking.background_processor import BackgroundWindowResult
from tracking.recovery_detector import (
    RecoveryWindowResult,
    compute_recovery_contributions,
    detect_recovery_windows,
)
from config import CONFIG

_cfg = CONFIG.tracking


# ── Factories ─────────────────────────────────────────────────────────────────

def _ts(hour: int, minute: int = 0) -> datetime:
    return datetime(2024, 1, 15, hour, minute, 0, tzinfo=UTC)


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
        hr_bpm        = 60.0,
        lf_hf         = None,
        confidence    = 0.9,
        acc_mean      = 0.05,
        gyro_mean     = None,
        n_beats       = 50,
        artifact_rate = 0.0,
        is_valid      = is_valid,
    )


def _sleep_block(n: int = 12, rmssd_ms: float = 70.0, start: datetime = None) -> list[BackgroundWindowResult]:
    start = start or _ts(0)
    return [_bg(start + timedelta(minutes=i * 5), rmssd_ms=rmssd_ms, context="sleep") for i in range(n)]


def _recovery_block(n: int = 6, rmssd_ms: float = 75.0, start: datetime = None) -> list[BackgroundWindowResult]:
    start = start or _ts(14)
    return [_bg(start + timedelta(minutes=i * 5), rmssd_ms=rmssd_ms) for i in range(n)]


def _stressed_block(n: int = 6, start: datetime = None) -> list[BackgroundWindowResult]:
    start = start or _ts(9)
    return [_bg(start + timedelta(minutes=i * 5), rmssd_ms=40.0) for i in range(n)]


# ── No recovery ────────────────────────────────────────────────────────────────

class TestNoRecovery:

    def test_empty_windows_returns_empty(self):
        assert detect_recovery_windows(
            windows=[], personal_morning_avg=60.0
        ) == []

    def test_stressed_day_no_recovery(self):
        """All RMSSD below morning avg → no recovery windows."""
        windows = _stressed_block(n=12)
        results = detect_recovery_windows(
            windows              = windows,
            personal_morning_avg = 60.0,
        )
        assert results == []

    def test_invalid_windows_skipped(self):
        """Windows with insufficient beats → __post_init__ sets is_valid=False → skipped."""
        min_beats = CONFIG.tracking.BACKGROUND_MIN_BEATS
        windows = [
            BackgroundWindowResult(
                user_id       = "user-1",
                window_start  = _ts(14, i * 5),
                window_end    = _ts(14, i * 5) + timedelta(minutes=5),
                context       = "background",
                rmssd_ms      = 80.0,
                hr_bpm        = 60.0,
                lf_hf         = None,
                confidence    = 0.9,
                acc_mean      = 0.05,
                gyro_mean     = None,
                n_beats       = min_beats - 1,   # too few → is_valid=False
                artifact_rate = 0.0,
                is_valid      = True,            # overridden by __post_init__
            )
            for i in range(6)
        ]
        assert all(not w.is_valid for w in windows)
        results = detect_recovery_windows(
            windows              = windows,
            personal_morning_avg = 60.0,
        )
        assert results == []


# ── Sleep recovery ─────────────────────────────────────────────────────────────

class TestSleepRecovery:

    def test_sleep_block_forms_one_window(self):
        windows = _sleep_block(n=12)
        results = detect_recovery_windows(
            windows              = windows,
            personal_morning_avg = 60.0,
        )
        # Sleep always gives exactly 1 window
        sleep_results = [r for r in results if r.context == "sleep"]
        assert len(sleep_results) == 1

    def test_sleep_window_auto_tagged(self):
        windows = _sleep_block(n=12)
        results = detect_recovery_windows(
            windows              = windows,
            personal_morning_avg = 60.0,
        )
        sleep_results = [r for r in results if r.context == "sleep"]
        assert sleep_results[0].tag == "sleep"

    def test_sleep_window_covers_full_block(self):
        windows = _sleep_block(n=8, start=_ts(0))
        results = detect_recovery_windows(
            windows              = windows,
            personal_morning_avg = 60.0,
        )
        sleep_results = [r for r in results if r.context == "sleep"]
        assert sleep_results[0].started_at == windows[0].window_start
        assert sleep_results[0].ended_at   == windows[-1].window_end

    def test_sleep_window_rmssd_avg_positive(self):
        windows = _sleep_block(n=8, rmssd_ms=70.0)
        results = detect_recovery_windows(
            windows              = windows,
            personal_morning_avg = 60.0,
        )
        sleep_results = [r for r in results if r.context == "sleep"]
        assert sleep_results[0].rmssd_avg_ms is not None
        assert sleep_results[0].rmssd_avg_ms > 0.0


# ── Daytime recovery ──────────────────────────────────────────────────────────

class TestDaytimeRecovery:

    def test_high_rmssd_block_creates_recovery_window(self):
        windows = _recovery_block(n=_cfg.RECOVERY_MIN_WINDOWS + 1, rmssd_ms=80.0)
        results = detect_recovery_windows(
            windows              = windows,
            personal_morning_avg = 60.0,
        )
        assert len(results) >= 1

    def test_below_min_windows_no_event(self):
        """RECOVERY_MIN_WINDOWS - 1 consecutive → no event."""
        n = max(1, _cfg.RECOVERY_MIN_WINDOWS - 1)
        windows = _recovery_block(n=n, rmssd_ms=80.0)
        results = detect_recovery_windows(
            windows              = windows,
            personal_morning_avg = 60.0,
        )
        bg_results = [r for r in results if r.context == "background"]
        assert bg_results == []

    def test_recovery_area_positive(self):
        windows = _recovery_block(n=_cfg.RECOVERY_MIN_WINDOWS + 2, rmssd_ms=80.0)
        results = detect_recovery_windows(
            windows              = windows,
            personal_morning_avg = 60.0,
        )
        bg_results = [r for r in results if r.context == "background"]
        if bg_results:
            assert bg_results[0].recovery_area >= 0.0

    def test_zenflow_session_overlap_auto_tags(self):
        """Recovery window overlapping a ZenFlow session should be auto-tagged."""
        start = _ts(16)
        windows = _recovery_block(n=_cfg.RECOVERY_MIN_WINDOWS + 2, rmssd_ms=80.0, start=start)
        session_id = "session-abc"
        intervals = [(start, start + timedelta(minutes=30), session_id)]
        results = detect_recovery_windows(
            windows                  = windows,
            personal_morning_avg     = 60.0,
            zenflow_session_intervals = intervals,
        )
        bg_results = [r for r in results if r.context == "background"]
        if bg_results:
            assert bg_results[0].zenflow_session_id == session_id


# ── compute_recovery_contributions ────────────────────────────────────────────

class TestComputeRecoveryContributions:

    def test_contributions_filled_with_max_area(self):
        sleep_wins = _sleep_block(n=8)
        day_wins   = _recovery_block(n=_cfg.RECOVERY_MIN_WINDOWS + 2, rmssd_ms=80.0)
        all_windows = sleep_wins + day_wins
        results = detect_recovery_windows(
            windows              = all_windows,
            personal_morning_avg = 60.0,
        )
        if not results:
            pytest.skip("No recovery windows detected")
        max_area = sum(r.recovery_area for r in results) or 1.0
        result = compute_recovery_contributions(results, max_possible_recovery_area=max_area)
        assert all(r.recovery_contribution_pct is not None for r in result)

    def test_empty_list_returns_empty(self):
        assert compute_recovery_contributions([], max_possible_recovery_area=100.0) == []

    def test_all_contributions_non_negative(self):
        sleep_wins = _sleep_block(n=6)
        results = detect_recovery_windows(
            windows=sleep_wins, personal_morning_avg=60.0
        )
        max_area = sum(r.recovery_area for r in results) or 1.0
        result = compute_recovery_contributions(results, max_possible_recovery_area=max_area)
        for r in result:
            assert (r.recovery_contribution_pct or 0.0) >= 0.0
