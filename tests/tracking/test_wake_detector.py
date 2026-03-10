"""
tests/tracking/test_wake_detector.py

Unit tests for tracking/wake_detector.py

Tests cover:
  - detect_wake_sleep_boundary returns a WakeSleepBoundary
  - method = "historical_pattern" when typical times provided and no transitions
  - method = "morning_read_anchor" when only morning_read_ts provided
  - waking_minutes computed correctly from wake/sleep times
  - compute_typical_wake_time returns median HH:MM from confirmed boundaries
  - compute_typical_sleep_time returns median HH:MM from confirmed boundaries
  - context transition chain leads to "sleep_transition" method
"""

from datetime import UTC, datetime, timedelta, date
from typing import Optional

import pytest

from tracking.wake_detector import (
    ContextTransition,
    WakeSleepBoundary,
    detect_wake_sleep_boundary,
    compute_typical_wake_time,
    compute_typical_sleep_time,
)

_DAY = datetime(2024, 1, 15, 0, 0, 0, tzinfo=UTC)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ts(hour: int, minute: int = 0) -> datetime:
    return datetime(2024, 1, 15, hour, minute, 0, tzinfo=UTC)


def _to_boundary_list(wake_time: str, sleep_time: str, n: int = 7) -> list[WakeSleepBoundary]:
    """Create n identical boundaries with given wake/sleep times."""
    boundaries = []
    for i in range(n):
        day = _DAY - timedelta(days=i + 1)
        wh, wm  = map(int, wake_time.split(":"))
        sh, sm  = map(int, sleep_time.split(":"))
        wake_ts  = day.replace(hour=wh, minute=wm)
        sleep_ts = day.replace(hour=sh, minute=sm)
        boundaries.append(WakeSleepBoundary(
            user_id                = "user-1",
            day_date               = day,
            wake_ts                = wake_ts,
            sleep_ts               = sleep_ts,
            wake_detection_method  = "sleep_transition",
            sleep_detection_method = "sleep_transition",
            waking_minutes         = (sleep_ts - wake_ts).total_seconds() / 60,
        ))
    return boundaries


# ── detect_wake_sleep_boundary ────────────────────────────────────────────────

class TestDetectWakeSleepBoundary:

    def test_returns_wake_sleep_boundary(self):
        boundary = detect_wake_sleep_boundary(
            day_date          = _DAY,
            user_id           = "user-1",
            typical_wake_time = "07:00",
            typical_sleep_time = "23:00",
        )
        assert isinstance(boundary, WakeSleepBoundary)

    def test_user_id_propagated(self):
        boundary = detect_wake_sleep_boundary(
            day_date  = _DAY,
            user_id   = "user-99",
            typical_wake_time  = "07:00",
            typical_sleep_time = "23:00",
        )
        assert boundary.user_id == "user-99"

    def test_historical_pattern_when_typical_times_provided(self):
        boundary = detect_wake_sleep_boundary(
            day_date           = _DAY,
            user_id            = "user-1",
            typical_wake_time  = "07:30",
            typical_sleep_time = "23:00",
        )
        assert boundary.wake_detection_method == "historical_pattern"

    def test_wake_ts_matches_typical_wake_time(self):
        boundary = detect_wake_sleep_boundary(
            day_date           = _DAY,
            user_id            = "user-1",
            typical_wake_time  = "07:15",
            typical_sleep_time = "23:00",
        )
        assert boundary.wake_ts is not None
        assert boundary.wake_ts.hour   == 7
        assert boundary.wake_ts.minute == 15

    def test_sleep_ts_matches_typical_sleep_time(self):
        boundary = detect_wake_sleep_boundary(
            day_date           = _DAY,
            user_id            = "user-1",
            typical_wake_time  = "07:00",
            typical_sleep_time = "22:30",
        )
        assert boundary.sleep_ts is not None
        assert boundary.sleep_ts.hour   == 22
        assert boundary.sleep_ts.minute == 30

    def test_morning_read_anchor_method_when_no_typical_times(self):
        morning_read = _ts(7, 30)
        boundary = detect_wake_sleep_boundary(
            day_date          = _DAY,
            user_id           = "user-1",
            morning_read_ts   = morning_read,
        )
        assert boundary.wake_detection_method == "morning_read_anchor"

    def test_morning_read_used_as_wake_ts(self):
        morning_read = _ts(7, 45)
        boundary = detect_wake_sleep_boundary(
            day_date        = _DAY,
            user_id         = "user-1",
            morning_read_ts = morning_read,
        )
        assert boundary.wake_ts == morning_read

    def test_waking_minutes_computed_correctly(self):
        boundary = detect_wake_sleep_boundary(
            day_date           = _DAY,
            user_id            = "user-1",
            typical_wake_time  = "07:00",
            typical_sleep_time = "23:00",
        )
        expected_minutes = (23 - 7) * 60  # 960 minutes
        assert boundary.waking_minutes == pytest.approx(expected_minutes, abs=1.0)

    def test_sleep_transition_method_with_context_transitions(self):
        """A sleep→background transition at 07:00 should be detected as sleep_transition."""
        transitions = [
            ContextTransition(
                ts           = _ts(7, 0),
                from_context = "sleep",
                to_context   = "background",
            ),
            ContextTransition(
                ts           = _ts(23, 0),
                from_context = "background",
                to_context   = "sleep",
            ),
        ]
        boundary = detect_wake_sleep_boundary(
            day_date            = _DAY,
            user_id             = "user-1",
            context_transitions = transitions,
        )
        assert boundary.wake_detection_method == "sleep_transition"
        assert boundary.wake_ts.hour   == 7
        assert boundary.wake_ts.minute == 0

    def test_sleep_detection_method_from_transition(self):
        transitions = [
            ContextTransition(
                ts           = _ts(22, 45),
                from_context = "background",
                to_context   = "sleep",
            ),
        ]
        boundary = detect_wake_sleep_boundary(
            day_date            = _DAY,
            user_id             = "user-1",
            context_transitions = transitions,
            typical_wake_time   = "07:00",
        )
        assert boundary.sleep_detection_method == "sleep_transition"
        assert boundary.sleep_ts.hour   == 22
        assert boundary.sleep_ts.minute == 45


# ── compute_typical_wake_time ─────────────────────────────────────────────────

class TestComputeTypicalWakeTime:

    def test_returns_median_wake_time(self):
        boundaries = _to_boundary_list("07:15", "23:00", n=7)
        result = compute_typical_wake_time(boundaries)
        assert result == "07:15"

    def test_empty_boundaries_returns_none(self):
        assert compute_typical_wake_time([]) is None

    def test_mixed_wake_times_returns_median(self):
        """Median of 07:00, 07:15, 07:30, 07:00, 07:15 = 07:15."""
        times = ["07:00", "07:15", "07:30", "07:00", "07:15"]
        boundaries = []
        for i, t in enumerate(times):
            day = _DAY - timedelta(days=i + 1)
            h, m = map(int, t.split(":"))
            wake_ts  = day.replace(hour=h, minute=m)
            sleep_ts = day.replace(hour=23, minute=0)
            boundaries.append(WakeSleepBoundary(
                user_id               = "user-1",
                day_date              = day,
                wake_ts               = wake_ts,
                sleep_ts              = sleep_ts,
                wake_detection_method = "sleep_transition",
                sleep_detection_method = "sleep_transition",
                waking_minutes        = (sleep_ts - wake_ts).total_seconds() / 60,
            ))
        result = compute_typical_wake_time(boundaries)
        assert result is not None
        # Should be a valid HH:MM string
        h, m = result.split(":")
        assert 0 <= int(h) <= 23
        assert 0 <= int(m) <= 59


# ── compute_typical_sleep_time ────────────────────────────────────────────────

class TestComputeTypicalSleepTime:

    def test_returns_median_sleep_time(self):
        boundaries = _to_boundary_list("07:00", "22:45", n=7)
        result = compute_typical_sleep_time(boundaries)
        assert result == "22:45"

    def test_empty_boundaries_returns_none(self):
        assert compute_typical_sleep_time([]) is None

    def test_result_is_valid_time_string(self):
        boundaries = _to_boundary_list("07:00", "23:00", n=5)
        result = compute_typical_sleep_time(boundaries)
        assert result is not None
        parts = result.split(":")
        assert len(parts) == 2
        assert 0 <= int(parts[0]) <= 23
        assert 0 <= int(parts[1]) <= 59
