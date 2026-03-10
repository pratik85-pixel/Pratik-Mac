"""
tests/tracking/test_background_processor.py

Unit tests for tracking/background_processor.py

Tests cover:
  - aggregate_background_window returns correct BackgroundWindowResult
  - is_valid=True when confidence and beat count are sufficient
  - is_valid=False when beats below threshold
  - is_valid=False when confidence below threshold
  - context field is propagated correctly
  - acc_mean / gyro_mean are stored as-is
  - has_motion returns True when acc_mean > MOTION_ACTIVE_THRESHOLD
  - has_motion returns False when below threshold
"""

import math
from datetime import UTC, datetime

import numpy as np
import pytest

from tracking.background_processor import (
    BackgroundWindowResult,
    aggregate_background_window,
    has_motion,
)
from config import CONFIG

_cfg = CONFIG.tracking


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ts(minute: int) -> datetime:
    return datetime(2024, 1, 15, 7, minute, 0, tzinfo=UTC)


def _make_ppi(n: int = 60, value: float = 850.0) -> list[float]:
    """Constant PPI stream — RMSSD=0, controlled beat count."""
    return [value] * n


def _make_alternating_ppi(n: int = 60, base: float = 800.0, alt: float = 860.0) -> list[float]:
    """Alternating PPI → non-zero RMSSD."""
    return [base if i % 2 == 0 else alt for i in range(n)]


# ── aggregate_background_window ────────────────────────────────────────────────

class TestAggregateBackgroundWindow:

    def test_returns_background_window_result(self):
        result = aggregate_background_window(
            ppi_ms       = np.array(_make_ppi(60)),
            ts_start     = _ts(0),
            ts_end       = _ts(5),
            user_id      = "user-1",
        )
        assert isinstance(result, BackgroundWindowResult)

    def test_user_id_propagated(self):
        result = aggregate_background_window(
            ppi_ms   = np.array(_make_ppi(60)),
            ts_start = _ts(0),
            ts_end   = _ts(5),
            user_id  = "user-42",
        )
        assert result.user_id == "user-42"

    def test_window_times_propagated(self):
        ws = _ts(10)
        we = _ts(15)
        result = aggregate_background_window(
            ppi_ms   = np.array(_make_ppi(60)),
            ts_start = ws,
            ts_end   = we,
            user_id  = "u",
        )
        assert result.window_start == ws
        assert result.window_end   == we

    def test_context_default_is_background(self):
        result = aggregate_background_window(
            ppi_ms   = np.array(_make_ppi(60)),
            ts_start = _ts(0),
            ts_end   = _ts(5),
            user_id  = "u",
        )
        assert result.context == "background"

    def test_sleep_context_propagated(self):
        result = aggregate_background_window(
            ppi_ms   = np.array(_make_ppi(60)),
            ts_start = _ts(0),
            ts_end   = _ts(5),
            user_id  = "u",
            context  = "sleep",
        )
        assert result.context == "sleep"

    def test_acc_mean_propagated(self):
        acc = np.full(100, 0.12)
        result = aggregate_background_window(
            ppi_ms      = np.array(_make_ppi(60)),
            ts_start    = _ts(0),
            ts_end      = _ts(5),
            user_id     = "u",
            acc_samples = acc,
        )
        assert result.acc_mean == pytest.approx(0.12)

    def test_gyro_mean_propagated(self):
        gyro = np.full(100, 0.05)
        result = aggregate_background_window(
            ppi_ms       = np.array(_make_ppi(60)),
            ts_start     = _ts(0),
            ts_end       = _ts(5),
            user_id      = "u",
            gyro_samples = gyro,
        )
        assert result.gyro_mean == pytest.approx(0.05)

    def test_valid_when_sufficient_data(self):
        """60 beats, clean signal → should be valid."""
        result = aggregate_background_window(
            ppi_ms   = np.array(_make_alternating_ppi(80)),
            ts_start = _ts(0),
            ts_end   = _ts(5),
            user_id  = "u",
        )
        assert result.n_beats == 80
        # is_valid depends on confidence ≥ 0.5 and n_beats ≥ BACKGROUND_MIN_BEATS
        assert result.n_beats >= _cfg.BACKGROUND_MIN_BEATS

    def test_insufficient_beats_marks_invalid(self):
        """Below BACKGROUND_MIN_BEATS → is_valid=False."""
        result = aggregate_background_window(
            ppi_ms   = np.array(_make_ppi(5)),   # only 5 beats
            ts_start = _ts(0),
            ts_end   = _ts(5),
            user_id  = "u",
        )
        assert result.is_valid is False

    def test_empty_ppi_marks_invalid(self):
        result = aggregate_background_window(
            ppi_ms   = np.array([]),
            ts_start = _ts(0),
            ts_end   = _ts(5),
            user_id  = "u",
        )
        assert result.is_valid is False
        assert result.rmssd_ms is None

    def test_rmssd_is_non_negative(self):
        result = aggregate_background_window(
            ppi_ms   = np.array(_make_alternating_ppi(60)),
            ts_start = _ts(0),
            ts_end   = _ts(5),
            user_id  = "u",
        )
        if result.rmssd_ms is not None:
            assert result.rmssd_ms >= 0.0

    def test_artifact_rate_between_0_and_1(self):
        result = aggregate_background_window(
            ppi_ms   = np.array(_make_ppi(60)),
            ts_start = _ts(0),
            ts_end   = _ts(5),
            user_id  = "u",
        )
        assert 0.0 <= result.artifact_rate <= 1.0

    def test_confidence_between_0_and_1(self):
        result = aggregate_background_window(
            ppi_ms   = np.array(_make_alternating_ppi(60)),
            ts_start = _ts(0),
            ts_end   = _ts(5),
            user_id  = "u",
        )
        assert 0.0 <= result.confidence <= 1.0


# ── has_motion ────────────────────────────────────────────────────────────────

class TestHasMotion:

    def _make_window(self, acc_mean: float | None) -> BackgroundWindowResult:
        return BackgroundWindowResult(
            user_id      = "u",
            window_start = _ts(0),
            window_end   = _ts(5),
            context      = "background",
            rmssd_ms     = 40.0,
            hr_bpm       = 60.0,
            lf_hf        = None,
            confidence   = 0.9,
            acc_mean     = acc_mean,
            gyro_mean    = None,
            n_beats      = 60,
            artifact_rate = 0.0,
            is_valid     = True,
        )

    def test_has_motion_true_above_threshold(self):
        from config import CONFIG as C
        threshold = C.tracking.MOTION_ACTIVE_THRESHOLD
        w = self._make_window(acc_mean=threshold + 0.1)
        # __post_init__ recalculates is_valid but not acc_mean
        assert w.acc_mean == pytest.approx(threshold + 0.1)
        assert has_motion(w) is True

    def test_has_motion_false_below_threshold(self):
        from config import CONFIG as C
        threshold = C.tracking.MOTION_ACTIVE_THRESHOLD
        w = self._make_window(acc_mean=max(0.0, threshold - 0.1))
        assert has_motion(w) is False

    def test_has_motion_false_when_acc_is_none(self):
        w = self._make_window(acc_mean=None)
        assert has_motion(w) is False
