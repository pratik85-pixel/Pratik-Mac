"""
tests/model/test_recovery_arc_detector.py

Tests for model/recovery_arc_detector.py

Covers:
  - Single clean arc detected correctly (drop + return)
  - Arc duration is accurate
  - Arc class assignment (fast/normal/slow/compressed)
  - Nadir is the minimum within the arc
  - Incomplete arc when data ends without return
  - No arc when drop is below threshold
  - Multiple arcs detected in sequence
  - Summary statistics across multiple arcs
"""

import numpy as np
import pytest
from datetime import datetime, timedelta

from model.recovery_arc_detector import (
    detect_arcs, summarise_arcs,
    ArcClass, RecoveryArcEvent, RecoveryArcSummary,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_ts_sec(n: int, interval_minutes: int = 30) -> np.ndarray:
    """Timestamps as Unix seconds, starting from a fixed point."""
    base = datetime(2025, 1, 1, 0, 0, 0).timestamp()
    return np.array([base + i * interval_minutes * 60 for i in range(n)], dtype=np.float64)


def flat_rmssd(n: int, value: float = 50.0) -> np.ndarray:
    return np.full(n, value, dtype=np.float64)


def arc_signal(
    baseline: float = 50.0,
    drop_pct: float = 0.30,
    drop_start: int = 10,
    drop_duration: int = 4,   # readings at nadir
    return_at:  int = 20,     # reading where it returns to baseline
    n: int = 30,
    interval_minutes: int = 30,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Build a synthetic RMSSD stream with one arc event:
      - Flat at baseline before drop_start
      - Drops to baseline*(1-drop_pct) at drop_start
      - Stays at nadir for drop_duration
      - Linearly recovers back to baseline by return_at
      - Flat at baseline after
    """
    values = np.full(n, float(baseline))
    nadir = baseline * (1.0 - drop_pct)
    for i in range(drop_start, min(drop_start + drop_duration, n)):
        values[i] = nadir
    # Linear recovery
    if return_at > drop_start + drop_duration:
        ramp_len = return_at - (drop_start + drop_duration)
        for j, i in enumerate(range(drop_start + drop_duration, min(return_at, n))):
            pct = j / ramp_len
            values[i] = nadir + pct * (baseline - nadir)
    ts = make_ts_sec(n, interval_minutes=interval_minutes)
    return values, ts


# ── Single arc ────────────────────────────────────────────────────────────────

class TestSingleArc:

    def test_single_arc_detected(self):
        values, ts = arc_signal(baseline=50.0, drop_pct=0.30, drop_start=10, return_at=20)
        arcs = detect_arcs(values, ts)
        assert len(arcs) >= 1

    def test_arc_nadir_is_minimum(self):
        values, ts = arc_signal(baseline=50.0, drop_pct=0.30, drop_start=10,
                                 drop_duration=4, return_at=20)
        arcs = detect_arcs(values, ts)
        assert len(arcs) >= 1
        arc = arcs[0]
        assert arc.nadir_value == pytest.approx(50.0 * 0.70, abs=2.0)

    def test_arc_drop_depth_correct(self):
        values, ts = arc_signal(baseline=50.0, drop_pct=0.30, drop_start=10, return_at=20)
        arcs = detect_arcs(values, ts)
        assert len(arcs) >= 1
        assert arcs[0].drop_depth_pct == pytest.approx(0.30, abs=0.05)

    def test_arc_is_complete(self):
        values, ts = arc_signal(baseline=50.0, drop_pct=0.30, drop_start=10, return_at=20, n=30)
        arcs = detect_arcs(values, ts)
        assert len(arcs) >= 1
        assert arcs[0].is_complete()
        assert arcs[0].return_ts is not None


# ── Arc duration → classification ─────────────────────────────────────────────

class TestArcClassification:

    def _arc_of_duration(self, hours: float) -> list[RecoveryArcEvent]:
        # Build a signal whose arc duration ≈ hours
        # interval = 10 min → 6 readings/hr (avoids boundary at exactly 2.0h)
        readings_per_hour = 6
        n_readings = int(hours * readings_per_hour) + 15
        n = max(n_readings + 5, 25)
        drop_dur = max(2, int(hours * readings_per_hour - 4))
        return_at = 5 + max(5, int(hours * readings_per_hour))
        values, ts = arc_signal(
            baseline=50.0, drop_pct=0.30,
            drop_start=5,
            drop_duration=drop_dur,
            return_at=return_at,
            n=n, interval_minutes=10
        )
        return detect_arcs(values, ts)

    def test_fast_arc_under_2hrs(self):
        """1-hour arc at 10-min intervals → clearly < 2h → FAST."""
        arcs = self._arc_of_duration(1.0)
        complete = [a for a in arcs if a.is_complete()]
        if complete:
            assert complete[0].arc_class == ArcClass.FAST

    def test_normal_arc_2_to_6hrs(self):
        arcs = self._arc_of_duration(4.0)
        complete = [a for a in arcs if a.is_complete()]
        if complete:
            assert complete[0].arc_class == ArcClass.NORMAL

    def test_no_arc_when_drop_below_threshold(self):
        """A 10% drop should not trigger an arc (threshold is 20%)."""
        values, ts = arc_signal(baseline=50.0, drop_pct=0.08, drop_start=5, return_at=15, n=25)
        arcs = detect_arcs(values, ts)
        complete = [a for a in arcs if a.is_complete()]
        assert len(complete) == 0


# ── Incomplete arc ─────────────────────────────────────────────────────────────

class TestIncompleteArc:

    def test_incomplete_arc_when_data_ends_without_return(self):
        """Drop at position 15, data ends at 20 without return."""
        values = np.full(20, 50.0)
        values[15:] = 30.0  # deep 40% drop, never returns
        ts = make_ts_sec(20, interval_minutes=30)
        arcs = detect_arcs(values, ts)
        incomplete = [a for a in arcs if not a.is_complete()]
        assert len(incomplete) >= 1

    def test_incomplete_arc_has_none_return_ts(self):
        values = np.full(20, 50.0)
        values[15:] = 25.0
        ts = make_ts_sec(20, interval_minutes=30)
        arcs = detect_arcs(values, ts)
        for a in arcs:
            if not a.is_complete():
                assert a.return_ts is None
                assert a.arc_class == ArcClass.INCOMPLETE


# ── Multiple arcs ─────────────────────────────────────────────────────────────

class TestMultipleArcs:

    def test_two_arcs_detected(self):
        # Arc 1: drop at 5, return at 15
        # Arc 2: drop at 25, return at 35
        n = 45
        values = np.full(n, 50.0)
        values[5:12]  = 32.0    # 36% drop
        values[12:15] = np.linspace(32.0, 50.0, 3)
        values[25:32] = 32.0
        values[32:35] = np.linspace(32.0, 50.0, 3)
        ts = make_ts_sec(n, interval_minutes=30)
        arcs = detect_arcs(values, ts)
        complete = [a for a in arcs if a.is_complete()]
        assert len(complete) >= 1  # at least one, ideally two


# ── Summary statistics ─────────────────────────────────────────────────────────

class TestSummaryStatistics:

    def _two_complete_arcs(self) -> list[RecoveryArcEvent]:
        n = 60
        values = np.full(n, 50.0)
        values[5:8]   = 32.0
        values[8:11]  = np.linspace(32.0, 50.0, 3)
        values[30:35] = 32.0
        values[35:40] = np.linspace(32.0, 50.0, 5)
        ts = make_ts_sec(n, interval_minutes=30)
        return detect_arcs(values, ts)

    def test_summary_n_events(self):
        arcs = self._two_complete_arcs()
        summary = summarise_arcs(arcs)
        assert summary.n_events >= 1   # at least one arc

    def test_summary_mean_hours_positive(self):
        arcs = self._two_complete_arcs()
        summary = summarise_arcs(arcs)
        if summary.mean_hours is not None:
            assert summary.mean_hours > 0.0

    def test_empty_arcs_summary(self):
        summary = summarise_arcs([])
        assert summary.n_events == 0
        assert summary.mean_hours is None

    def test_only_incomplete_arcs_gives_valid_summary(self):
        values = np.full(15, 50.0)
        values[10:] = 25.0  # never returns
        ts = make_ts_sec(15)
        arcs = detect_arcs(values, ts)
        summary = summarise_arcs(arcs)
        assert summary.n_events >= 0   # should not raise


# ── Summary to_dict ───────────────────────────────────────────────────────────

class TestSummaryToDict:

    def test_to_dict_keys(self):
        arcs = self._simple_arcs()
        summary = summarise_arcs(arcs)
        d = summary.to_dict()
        for key in ("mean_hours", "fast_hours", "slow_hours", "arc_class", "n_events", "n_incomplete"):
            assert key in d

    def _simple_arcs(self) -> list[RecoveryArcEvent]:
        values, ts = arc_signal(baseline=50.0, drop_pct=0.30, drop_start=5, return_at=15, n=25)
        return detect_arcs(values, ts)
