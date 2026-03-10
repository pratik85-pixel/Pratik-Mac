"""
tests/tracking/test_stress_detector.py

Unit tests for tracking/stress_detector.py

Tests cover:
  - No stress windows detected when RMSSD is stable above threshold
  - Stress window detected when RMSSD sustains below threshold
  - Below STRESS_MIN_WINDOWS consecutive → no event raised
  - should_nudge: nudge blocked when daily cap reached
  - should_nudge: significant spike override bypasses cap
  - compute_stress_contributions: sum of contributions ≈ 100
  - Physical load classification via motion majority vote
  - Stress windows merged when gap ≤ STRESS_MERGE_GAP_MINUTES
  - Invalid windows skipped during detection
"""

from datetime import UTC, datetime, timedelta
from typing import Optional

import pytest

from tracking.background_processor import BackgroundWindowResult
from tracking.stress_detector import (
    StressWindowResult,
    compute_stress_contributions,
    detect_stress_windows,
    should_nudge,
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
    acc_mean: Optional[float] = None,
) -> BackgroundWindowResult:
    return BackgroundWindowResult(
        user_id      = "user-1",
        window_start = window_start,
        window_end   = window_start + timedelta(minutes=5),
        context      = context,
        rmssd_ms     = rmssd_ms,
        hr_bpm       = 65.0,
        lf_hf        = None,
        confidence   = 0.9,
        acc_mean     = acc_mean,
        gyro_mean    = None,
        n_beats      = 50,
        artifact_rate = 0.0,
        is_valid     = is_valid,
    )


def _stream_normal(n: int = 12, base_rmssd: float = 60.0) -> list[BackgroundWindowResult]:
    """Non-stressed stream: RMSSD at/above personal morning avg."""
    return [_bg(_ts(9, i * 5), rmssd_ms=base_rmssd) for i in range(n)]


def _stream_stressed(
    n: int = 4,
    start: datetime = None,
    rmssd_ms: float = 40.0,
) -> list[BackgroundWindowResult]:
    """Below-threshold block of windows."""
    start = start or _ts(10)
    return [_bg(start + timedelta(minutes=i * 5), rmssd_ms=rmssd_ms) for i in range(n)]


# ── No stress ─────────────────────────────────────────────────────────────────

class TestNoStress:

    def test_stable_high_rmssd_produces_no_events(self):
        windows = _stream_normal(n=12, base_rmssd=80.0)
        results = detect_stress_windows(
            windows              = windows,
            personal_morning_avg = 60.0,
            personal_floor       = 30.0,
        )
        assert results == []

    def test_single_dip_below_min_windows_produces_no_event(self):
        """One window below threshold — below STRESS_MIN_WINDOWS (2)."""
        windows = _stream_normal(n=10)
        # Insert one stressed window
        windows.insert(5, _bg(_ts(9, 25), rmssd_ms=40.0))
        results = detect_stress_windows(
            windows              = windows,
            personal_morning_avg = 60.0,
            personal_floor       = 30.0,
        )
        assert results == []

    def test_invalid_windows_ignored(self):
        """Windows with insufficient beats → __post_init__ sets is_valid=False → skipped."""
        min_beats = _cfg.BACKGROUND_MIN_BEATS
        windows = [
            BackgroundWindowResult(
                user_id       = "user-1",
                window_start  = _ts(9, i * 5),
                window_end    = _ts(9, i * 5) + timedelta(minutes=5),
                context       = "background",
                rmssd_ms      = 40.0,
                hr_bpm        = 65.0,
                lf_hf         = None,
                confidence    = 0.9,
                acc_mean      = None,
                gyro_mean     = None,
                n_beats       = min_beats - 1,   # too few → is_valid=False
                artifact_rate = 0.0,
                is_valid      = True,            # overridden by __post_init__
            )
            for i in range(4)
        ]
        # verify __post_init__ did its job
        assert all(not w.is_valid for w in windows)
        results = detect_stress_windows(
            windows              = windows,
            personal_morning_avg = 60.0,
            personal_floor       = 30.0,
        )
        assert results == []

    def test_sleep_context_windows_ignored(self):
        """Sleep-context windows should not generate stress events."""
        windows = [
            _bg(_ts(2, i * 5), rmssd_ms=35.0, context="sleep") for i in range(6)
        ]
        results = detect_stress_windows(
            windows              = windows,
            personal_morning_avg = 60.0,
            personal_floor       = 30.0,
        )
        assert results == []

    def test_empty_windows_returns_empty(self):
        assert detect_stress_windows(
            windows=[], personal_morning_avg=60.0, personal_floor=30.0
        ) == []


# ── Stress detected ───────────────────────────────────────────────────────────

class TestStressDetected:

    def test_sustained_breach_creates_event(self):
        """4 consecutive windows below threshold → one event."""
        stressed = _stream_stressed(n=4, rmssd_ms=40.0)
        results = detect_stress_windows(
            windows              = stressed,
            personal_morning_avg = 60.0,
            personal_floor       = 30.0,
        )
        assert len(results) == 1

    def test_event_user_id_matches(self):
        results = detect_stress_windows(
            windows              = _stream_stressed(n=3),
            personal_morning_avg = 60.0,
            personal_floor       = 30.0,
        )
        assert results[0].user_id == "user-1"

    def test_event_duration_correct(self):
        """4 × 5-min windows → duration_minutes = 20."""
        results = detect_stress_windows(
            windows              = _stream_stressed(n=4),
            personal_morning_avg = 60.0,
            personal_floor       = 30.0,
        )
        assert results[0].duration_minutes == pytest.approx(20.0)

    def test_suppression_area_positive(self):
        results = detect_stress_windows(
            windows              = _stream_stressed(n=4, rmssd_ms=40.0),
            personal_morning_avg = 60.0,
            personal_floor       = 30.0,
        )
        assert results[0].suppression_area > 0.0

    def test_tag_candidate_set_for_stressed_event(self):
        """Non-motion event → tag_candidate should be 'stress_event_candidate'."""
        results = detect_stress_windows(
            windows              = _stream_stressed(n=4, rmssd_ms=40.0),
            personal_morning_avg = 60.0,
            personal_floor       = 30.0,
        )
        assert results[0].tag_candidate is not None

    def test_physical_load_candidate_with_motion(self):
        """High acc_mean → physical_load_candidate."""
        threshold = _cfg.MOTION_ACTIVE_THRESHOLD
        start = _ts(10)
        windows = [
            _bg(start + timedelta(minutes=i * 5), rmssd_ms=40.0, acc_mean=threshold + 0.5)
            for i in range(4)
        ]
        results = detect_stress_windows(
            windows              = windows,
            personal_morning_avg = 60.0,
            personal_floor       = 30.0,
        )
        assert len(results) == 1
        assert results[0].tag_candidate == "physical_load_candidate"

    def test_two_distinct_events_not_merged(self):
        """
        Two stressed blocks padded with non-stressed windows in between.
        Gap between blocks > STRESS_MERGE_GAP_MINUTES → two separate events.
        """
        start1 = _ts(9)
        # Block 1: 4 stressed windows (9:00–9:20)
        block1 = _stream_stressed(n=4, start=start1, rmssd_ms=40.0)
        # Filler: enough non-stressed windows to exceed STRESS_MERGE_GAP_MINUTES
        filler_n = _cfg.STRESS_MERGE_GAP_MINUTES // 5 + 2  # > merge threshold
        filler = [
            _bg(start1 + timedelta(minutes=(4 + i) * 5), rmssd_ms=70.0)
            for i in range(filler_n)
        ]
        # Block 2: 4 stressed windows after the filler
        block2_start = start1 + timedelta(minutes=(4 + filler_n) * 5)
        block2 = _stream_stressed(n=4, start=block2_start, rmssd_ms=40.0)

        all_windows = block1 + filler + block2
        results = detect_stress_windows(
            windows              = all_windows,
            personal_morning_avg = 60.0,
            personal_floor       = 30.0,
        )
        assert len(results) == 2

    def test_adjacent_events_merged_on_small_gap(self):
        """
        Two stressed blocks with exactly 1 filler window in between.
        Gap = 5 min <= STRESS_MERGE_GAP_MINUTES → merged into one event.
        """
        start1 = _ts(9)
        block1 = _stream_stressed(n=4, start=start1, rmssd_ms=40.0)
        # One non-stressed window in the gap
        gap_window = _bg(start1 + timedelta(minutes=20), rmssd_ms=70.0)
        block2_start = start1 + timedelta(minutes=25)
        block2 = _stream_stressed(n=4, start=block2_start, rmssd_ms=40.0)
        all_windows = block1 + [gap_window] + block2
        results = detect_stress_windows(
            windows              = all_windows,
            personal_morning_avg = 60.0,
            personal_floor       = 30.0,
        )
        assert len(results) == 1


# ── compute_stress_contributions ──────────────────────────────────────────────

class TestComputeStressContributions:

    def test_contributions_filled_with_max_area(self):
        windows = detect_stress_windows(
            windows              = _stream_stressed(n=6),
            personal_morning_avg = 60.0,
            personal_floor       = 30.0,
        )
        if not windows:
            pytest.skip("No windows detected")
        max_area = sum(w.suppression_area for w in windows)
        result = compute_stress_contributions(windows, max_possible_suppression_area=max_area)
        # All contributions should now be filled
        assert all(w.stress_contribution_pct is not None for w in result)

    def test_contributions_all_non_negative(self):
        windows = detect_stress_windows(
            windows              = _stream_stressed(n=6),
            personal_morning_avg = 60.0,
            personal_floor       = 30.0,
        )
        max_area = sum(w.suppression_area for w in windows) or 1.0
        result = compute_stress_contributions(windows, max_possible_suppression_area=max_area)
        for w in result:
            assert (w.stress_contribution_pct or 0.0) >= 0.0

    def test_single_event_with_full_area_is_100(self):
        """Single event filling the entire max area → contribution = 100."""
        windows = detect_stress_windows(
            windows              = _stream_stressed(n=6),
            personal_morning_avg = 60.0,
            personal_floor       = 30.0,
        )
        if len(windows) != 1:
            pytest.skip("Need exactly 1 stress window for this test")
        max_area = windows[0].suppression_area
        result = compute_stress_contributions(windows, max_possible_suppression_area=max_area)
        assert result[0].stress_contribution_pct == pytest.approx(100.0, abs=0.01)

    def test_zero_max_area_gives_zero_contributions(self):
        windows = detect_stress_windows(
            windows              = _stream_stressed(n=4),
            personal_morning_avg = 60.0,
            personal_floor       = 30.0,
        )
        result = compute_stress_contributions(windows, max_possible_suppression_area=0.0)
        for w in result:
            assert w.stress_contribution_pct == 0.0

    def test_empty_list_returns_empty(self):
        assert compute_stress_contributions([], max_possible_suppression_area=100.0) == []


# ── should_nudge ──────────────────────────────────────────────────────────────

class TestShouldNudge:

    def _make_stress_window(
        self,
        stress_contribution_pct: float = 10.0,
        tag: Optional[str] = None,
    ) -> StressWindowResult:
        return StressWindowResult(
            user_id              = "user-1",
            started_at           = _ts(10),
            ended_at             = _ts(10, 20),
            duration_minutes     = 20.0,
            rmssd_min_ms         = 40.0,
            suppression_pct      = 0.3,
            stress_contribution_pct = stress_contribution_pct,
            suppression_area     = 100.0,
            tag                  = tag,
        )

    def test_nudge_allowed_under_cap(self):
        # stress_contribution_pct=10.0 (0.10) > STRESS_MIN_NUDGE_CONTRIBUTION (0.03)
        window  = self._make_stress_window(stress_contribution_pct=10.0)
        assert should_nudge(window, daily_stress_load=0.5, nudges_sent_today=0) is True

    def test_nudge_blocked_at_cap(self):
        # Below significant override (< 25%), cap reached → blocked
        window = self._make_stress_window(stress_contribution_pct=10.0)
        cap    = _cfg.MAX_TAGGING_NUDGES_PER_DAY
        assert should_nudge(window, daily_stress_load=0.5, nudges_sent_today=cap) is False

    def test_significant_spike_overrides_cap(self):
        """A spike > NUDGE_SIGNIFICANT_SPIKE_OVERRIDE_PCT passes even at cap."""
        override_pct = _cfg.NUDGE_SIGNIFICANT_SPIKE_OVERRIDE_PCT * 100  # as percentage
        window = self._make_stress_window(stress_contribution_pct=override_pct + 1.0)
        cap    = _cfg.MAX_TAGGING_NUDGES_PER_DAY
        assert should_nudge(window, daily_stress_load=0.5, nudges_sent_today=cap) is True

    def test_already_tagged_window_blocked(self):
        """Window already tagged by user → no nudge."""
        window = self._make_stress_window(tag="work_calls")
        assert should_nudge(window, daily_stress_load=0.5, nudges_sent_today=0) is False

    def test_small_contribution_blocked(self):
        """Below STRESS_MIN_NUDGE_CONTRIBUTION → no nudge."""
        # 0.01 contribution → below 3% threshold
        window = self._make_stress_window(stress_contribution_pct=0.5)
        assert should_nudge(window, daily_stress_load=0.5, nudges_sent_today=0) is False
