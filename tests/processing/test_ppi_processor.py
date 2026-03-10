"""
tests/processing/test_ppi_processor.py

Unit tests for processing/ppi_processor.py

Tests cover:
  - RMSSD computation correctness (hand-calculated reference)
  - SDNN computation correctness
  - pNN50 computation correctness
  - Minimum beat guard (< 20 beats → confidence 0.0)
  - Confidence scaling with beat count and artifact rate
  - Windowed processing
  - classify_rmssd zones
"""

import numpy as np
import pytest

from processing.ppi_processor import (
    compute_ppi_metrics,
    process_window,
    classify_rmssd,
    PPIMetrics,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_constant_ppi(n: int = 60, value_ms: float = 800.0) -> np.ndarray:
    """Constant PPI stream — RMSSD and pNN50 should be 0."""
    return np.full(n, value_ms)


def make_ramps_of_50(n: int = 60) -> np.ndarray:
    """
    Alternating 800/850/800/850... so every diff is ±50ms.
    pNN50 should be exactly 0% (|diff| == 50, not > 50).
    RMSSD = 50.0
    """
    return np.array([800.0 if i % 2 == 0 else 850.0 for i in range(n)])


def make_ramps_over_50(n: int = 60) -> np.ndarray:
    """
    Alternating 800/851 so every diff is ±51ms.
    pNN50 should be 100%.
    RMSSD = 51.0
    """
    return np.array([800.0 if i % 2 == 0 else 851.0 for i in range(n)])


# ── RMSSD ─────────────────────────────────────────────────────────────────────

class TestRMSSD:

    def test_constant_stream_rmssd_is_zero(self):
        ppi = make_constant_ppi(60)
        result = compute_ppi_metrics(ppi)
        assert result.rmssd_ms == pytest.approx(0.0, abs=1e-6)

    def test_known_rmssd(self):
        """
        PPI = [800, 850, 800, 850, ...] for 60 beats.
        diffs = [±50, ±50, ...] for 59 diffs.
        RMSSD = sqrt(mean(50^2)) = 50.0
        """
        ppi = make_ramps_of_50(60)
        result = compute_ppi_metrics(ppi)
        assert result.rmssd_ms == pytest.approx(50.0, abs=1e-4)

    def test_rmssd_not_none_with_sufficient_beats(self):
        ppi = make_constant_ppi(20)
        result = compute_ppi_metrics(ppi)
        assert result.rmssd_ms is not None

    def test_rmssd_none_with_insufficient_beats(self):
        ppi = make_constant_ppi(19)
        result = compute_ppi_metrics(ppi)
        assert result.rmssd_ms is None
        assert result.confidence == 0.0


# ── SDNN ──────────────────────────────────────────────────────────────────────

class TestSDNN:

    def test_constant_stream_sdnn_is_zero(self):
        ppi = make_constant_ppi(60)
        result = compute_ppi_metrics(ppi)
        assert result.sdnn_ms == pytest.approx(0.0, abs=1e-6)

    def test_sdnn_positive_for_varying_ppi(self):
        ppi = make_ramps_of_50(60)
        result = compute_ppi_metrics(ppi)
        assert result.sdnn_ms > 0.0


# ── pNN50 ─────────────────────────────────────────────────────────────────────

class TestPNN50:

    def test_constant_stream_pnn50_is_zero(self):
        ppi = make_constant_ppi(60)
        result = compute_ppi_metrics(ppi)
        assert result.pnn50_pct == pytest.approx(0.0, abs=1e-6)

    def test_exactly_50ms_diff_not_counted(self):
        """
        pNN50 counts diffs STRICTLY > 50ms.
        Exactly 50ms should give pNN50 = 0%.
        """
        ppi = make_ramps_of_50(60)
        result = compute_ppi_metrics(ppi)
        assert result.pnn50_pct == pytest.approx(0.0, abs=1e-6)

    def test_over_50ms_diff_all_counted(self):
        ppi = make_ramps_over_50(60)
        result = compute_ppi_metrics(ppi)
        assert result.pnn50_pct == pytest.approx(100.0, abs=1e-4)


# ── Mean HR / PPI ─────────────────────────────────────────────────────────────

class TestMeanMetrics:

    def test_mean_ppi(self):
        ppi = np.array([800.0, 900.0, 1000.0] * 10)
        result = compute_ppi_metrics(ppi)
        assert result.mean_ppi_ms == pytest.approx(900.0, abs=1e-4)

    def test_mean_hr_at_60bpm(self):
        ppi = make_constant_ppi(60, value_ms=1000.0)
        result = compute_ppi_metrics(ppi)
        assert result.mean_hr_bpm == pytest.approx(60.0, abs=1e-4)

    def test_mean_hr_at_75bpm(self):
        ppi = make_constant_ppi(60, value_ms=800.0)
        result = compute_ppi_metrics(ppi)
        assert result.mean_hr_bpm == pytest.approx(75.0, abs=1e-4)


# ── Confidence ────────────────────────────────────────────────────────────────

class TestConfidence:

    def test_confidence_zero_below_min_beats(self):
        ppi = make_constant_ppi(5)
        result = compute_ppi_metrics(ppi)
        assert result.confidence == 0.0

    def test_confidence_increases_with_beats(self):
        r20  = compute_ppi_metrics(make_constant_ppi(20))
        r60  = compute_ppi_metrics(make_constant_ppi(60))
        r120 = compute_ppi_metrics(make_constant_ppi(120))
        assert r20.confidence < r60.confidence < r120.confidence

    def test_confidence_degrades_with_artifact_rate(self):
        ppi = make_constant_ppi(120)
        r_clean    = compute_ppi_metrics(ppi, artifact_rate=0.0)
        r_moderate = compute_ppi_metrics(ppi, artifact_rate=0.2)
        r_heavy    = compute_ppi_metrics(ppi, artifact_rate=0.5)
        assert r_clean.confidence > r_moderate.confidence > r_heavy.confidence

    def test_is_valid_with_sufficient_beats(self):
        ppi = make_constant_ppi(60)
        assert compute_ppi_metrics(ppi).is_valid()

    def test_not_valid_with_insufficient_beats(self):
        assert not compute_ppi_metrics(make_constant_ppi(5)).is_valid()


# ── Windowed Processing ────────────────────────────────────────────────────────

class TestProcessWindow:

    def test_window_extracts_correct_beats(self):
        """Beats at 0–60s into two equal windows."""
        n = 120
        ppi = np.full(n, 800.0)  # ~1 beat/800ms
        timestamps = np.linspace(0.0, 96.0, n)  # evenly spread

        result = process_window(ppi, timestamps, window_start_s=0.0, window_duration_s=48.0)
        # Should contain ~half the beats
        assert result.n_beats == pytest.approx(n // 2, abs=2)

    def test_window_returns_invalid_outside_data(self):
        ppi = make_constant_ppi(60)
        timestamps = np.linspace(0.0, 50.0, 60)
        result = process_window(ppi, timestamps, window_start_s=200.0, window_duration_s=60.0)
        assert not result.is_valid()


# ── classify_rmssd ─────────────────────────────────────────────────────────────

class TestClassifyRMSSD:

    def test_low_rmssd(self):
        result = classify_rmssd(10.0)
        assert result["label"] == "low"
        assert result["percentile_population"] < 10.0

    def test_above_average_rmssd(self):
        result = classify_rmssd(60.0)
        assert result["label"] == "above_average"

    def test_personal_range_midpoint(self):
        result = classify_rmssd(50.0, floor=0.0, ceiling=100.0)
        assert result["position_in_personal_range"] == pytest.approx(0.5, abs=0.01)

    def test_personal_range_at_ceiling(self):
        result = classify_rmssd(100.0, floor=0.0, ceiling=100.0)
        assert result["position_in_personal_range"] == pytest.approx(1.0, abs=0.01)

    def test_no_personal_range_when_not_provided(self):
        result = classify_rmssd(50.0)
        assert "position_in_personal_range" not in result
