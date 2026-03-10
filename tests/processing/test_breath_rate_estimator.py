"""
tests/processing/test_breath_rate_estimator.py

Tests for processing/breath_rate_estimator.py
"""

from __future__ import annotations

import numpy as np
import pytest

from processing.breath_rate_estimator import (
    BreathRateEstimate,
    estimate_breath_rate,
    gate_a_passes,
)


# ── Synthetic signal helpers ───────────────────────────────────────────────────

def _synthetic_ppi(
    breathing_bpm: float,
    duration_s: float = 60.0,
    hr_bpm: float = 60.0,
    rsa_amplitude_ms: float = 40.0,
    noise_ms: float = 2.0,
    seed: int = 42,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Generate a synthetic PPI series with a clear RSA oscillation at breathing_bpm.
    Returns (ppi_ms, timestamps_s).
    """
    rng = np.random.default_rng(seed)
    beat_period_s = 60.0 / hr_bpm
    n_beats = int(duration_s / beat_period_s)
    timestamps = np.cumsum(np.full(n_beats, beat_period_s))

    breathing_hz = breathing_bpm / 60.0
    rsa_wave = rsa_amplitude_ms * np.sin(2 * np.pi * breathing_hz * timestamps)

    base_ppi_ms = 60_000.0 / hr_bpm
    noise = rng.normal(0, noise_ms, n_beats)
    ppi_ms = base_ppi_ms + rsa_wave + noise

    return ppi_ms, timestamps


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestBreathRateEstimate:

    def test_is_valid_true(self):
        est = BreathRateEstimate(bpm=6.0, confidence=0.7, n_cycles=4)
        assert est.is_valid() is True

    def test_is_valid_false_none_bpm(self):
        est = BreathRateEstimate(bpm=None, confidence=0.8, n_cycles=0)
        assert est.is_valid() is False

    def test_is_valid_false_low_confidence(self):
        est = BreathRateEstimate(bpm=6.0, confidence=0.3, n_cycles=4)
        assert est.is_valid() is False


class TestEstimateBreathRate:

    def test_empty_arrays_returns_none(self):
        result = estimate_breath_rate(np.array([]), np.array([]))
        assert result.bpm is None
        assert result.confidence == 0.0
        assert result.method == "insufficient_data"

    def test_too_few_beats_returns_none(self):
        ppi = np.full(10, 1000.0)
        ts  = np.cumsum(np.full(10, 1.0))
        result = estimate_breath_rate(ppi, ts)
        assert result.bpm is None

    def test_mismatched_lengths_returns_none(self):
        ppi = np.full(30, 1000.0)
        ts  = np.arange(20, dtype=float)
        result = estimate_breath_rate(ppi, ts)
        assert result.bpm is None

    def test_detects_6_bpm(self):
        ppi, ts = _synthetic_ppi(breathing_bpm=6.0, duration_s=90.0, rsa_amplitude_ms=50.0)
        result = estimate_breath_rate(ppi, ts)
        assert result.bpm is not None
        assert abs(result.bpm - 6.0) <= 1.5, f"Expected ~6 BPM, got {result.bpm}"

    def test_detects_10_bpm(self):
        ppi, ts = _synthetic_ppi(breathing_bpm=10.0, duration_s=60.0, rsa_amplitude_ms=30.0)
        result = estimate_breath_rate(ppi, ts)
        assert result.bpm is not None
        assert abs(result.bpm - 10.0) <= 2.0, f"Expected ~10 BPM, got {result.bpm}"

    def test_confidence_increases_with_more_cycles(self):
        """Longer signal → more cycles → higher confidence."""
        ppi_short, ts_short = _synthetic_ppi(breathing_bpm=6.0, duration_s=30.0)
        ppi_long,  ts_long  = _synthetic_ppi(breathing_bpm=6.0, duration_s=90.0)

        result_short = estimate_breath_rate(ppi_short, ts_short)
        result_long  = estimate_breath_rate(ppi_long,  ts_long)

        if result_short.bpm is not None and result_long.bpm is not None:
            assert result_long.confidence >= result_short.confidence - 0.1

    def test_bpm_clamped_to_valid_range(self):
        """bpm should always be in [3, 24] range."""
        ppi, ts = _synthetic_ppi(breathing_bpm=8.0, duration_s=60.0)
        result = estimate_breath_rate(ppi, ts)
        if result.bpm is not None:
            assert 3.0 <= result.bpm <= 24.0

    def test_n_cycles_positive_on_valid_estimate(self):
        ppi, ts = _synthetic_ppi(breathing_bpm=6.0, duration_s=90.0, rsa_amplitude_ms=50.0)
        result = estimate_breath_rate(ppi, ts)
        if result.bpm is not None:
            assert result.n_cycles >= 2

    def test_pure_flat_signal_low_confidence(self):
        """Flat PPI (no RSA) should produce low confidence or no estimate."""
        ppi = np.full(60, 1000.0)
        ts  = np.arange(60, dtype=float)
        result = estimate_breath_rate(ppi, ts)
        if result.bpm is not None:
            assert result.confidence < 0.7


class TestGateA:

    def test_passes_within_tolerance(self):
        est = BreathRateEstimate(bpm=6.2, confidence=0.8, n_cycles=4)
        assert gate_a_passes(est, target_bpm=6.0, tolerance_bpm=1.5) is True

    def test_fails_outside_tolerance(self):
        est = BreathRateEstimate(bpm=8.0, confidence=0.8, n_cycles=4)
        assert gate_a_passes(est, target_bpm=6.0, tolerance_bpm=1.5) is False

    def test_fails_when_invalid_estimate(self):
        est = BreathRateEstimate(bpm=None, confidence=0.0, n_cycles=0)
        assert gate_a_passes(est, target_bpm=6.0) is False

    def test_fails_when_low_confidence(self):
        est = BreathRateEstimate(bpm=6.0, confidence=0.2, n_cycles=1)
        assert gate_a_passes(est, target_bpm=6.0) is False

    def test_exact_match_passes(self):
        est = BreathRateEstimate(bpm=6.0, confidence=0.9, n_cycles=5)
        assert gate_a_passes(est, target_bpm=6.0) is True

    def test_boundary_exactly_at_tolerance_passes(self):
        est = BreathRateEstimate(bpm=7.5, confidence=0.9, n_cycles=5)
        assert gate_a_passes(est, target_bpm=6.0, tolerance_bpm=1.5) is True

    def test_boundary_just_over_tolerance_fails(self):
        est = BreathRateEstimate(bpm=7.6, confidence=0.9, n_cycles=5)
        assert gate_a_passes(est, target_bpm=6.0, tolerance_bpm=1.5) is False
