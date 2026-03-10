"""
tests/processing/test_rsa_analyzer.py

Unit tests for processing/rsa_analyzer.py

Tests validate:
  - RSA power is detected in correct frequency band
  - Insufficient data guard
  - Windowed RSA computation
  - Responder persona has higher RSA power than Wire persona
  - Peak frequency is near 0.1 Hz when signal is generated at 0.1 Hz
"""

import numpy as np
import pytest

from processing.synthetic_generator import SyntheticPPIGenerator, PersonaType
from processing.rsa_analyzer import compute_rsa, compute_windowed_rsa


def get_persona_rsa(persona: PersonaType, duration_s: float = 120.0):
    gen = SyntheticPPIGenerator(persona=persona, seed=42)
    ppi, ts = gen.generate(duration_seconds=duration_s, include_artifacts=False)
    return compute_rsa(ppi, ts, artifact_rate=0.0)


# ── Basic validity ─────────────────────────────────────────────────────────────

class TestRSABasic:

    def test_baseline_persona_produces_valid_result(self):
        result = get_persona_rsa(PersonaType.BASELINE, duration_s=120.0)
        assert result.is_valid()
        assert result.rsa_power is not None
        assert result.rsa_power > 0.0

    def test_insufficient_beats_returns_invalid(self):
        ppi = np.full(10, 800.0)
        ts  = np.linspace(0.0, 8.0, 10)
        result = compute_rsa(ppi, ts)
        assert not result.is_valid()
        assert result.confidence == 0.0

    def test_total_power_is_positive(self):
        result = get_persona_rsa(PersonaType.BASELINE)
        assert result.total_hrv_power > 0.0

    def test_lf_hf_ratio_is_positive(self):
        result = get_persona_rsa(PersonaType.BASELINE)
        assert result.lf_hf_ratio is not None
        assert result.lf_hf_ratio > 0.0


# ── RSA power ordering across personas ────────────────────────────────────────

class TestRSAPowerOrdering:
    """
    Responder has highest RSA amplitude → highest RSA power.
    Wire has lowest RSA amplitude → lowest RSA power.
    """

    def test_responder_rsa_power_greater_than_wire(self):
        r_responder = get_persona_rsa(PersonaType.RESPONDER, duration_s=180.0)
        r_wire      = get_persona_rsa(PersonaType.WIRE,      duration_s=180.0)

        assert r_responder.is_valid()
        assert r_wire.is_valid()
        assert r_responder.rsa_power > r_wire.rsa_power

    def test_responder_beats_baseline_in_rsa(self):
        r_res = get_persona_rsa(PersonaType.RESPONDER, duration_s=180.0)
        r_bas = get_persona_rsa(PersonaType.BASELINE,  duration_s=180.0)
        assert r_res.rsa_power > r_bas.rsa_power


# ── Peak frequency near 0.1 Hz ─────────────────────────────────────────────────

class TestRSAPeakFrequency:

    def test_peak_frequency_near_01hz_for_baseline(self):
        """
        BASELINE persona is generated at exactly 0.1 Hz RSA.
        Peak should be within ±0.02 Hz of 0.1 Hz.
        """
        result = get_persona_rsa(PersonaType.BASELINE, duration_s=240.0)
        assert result.is_valid()
        assert abs(result.rsa_peak_freq_hz - 0.1) < 0.02

    def test_peak_frequency_in_rsa_band(self):
        result = get_persona_rsa(PersonaType.BASELINE, duration_s=120.0)
        assert 0.08 <= result.rsa_peak_freq_hz <= 0.12


# ── Confidence ────────────────────────────────────────────────────────────────

class TestRSAConfidence:

    def test_confidence_increases_with_duration(self):
        r60  = get_persona_rsa(PersonaType.BASELINE, duration_s=60.0)
        r120 = get_persona_rsa(PersonaType.BASELINE, duration_s=120.0)
        assert r120.confidence >= r60.confidence

    def test_confidence_near_1_for_long_clean_signal(self):
        result = get_persona_rsa(PersonaType.BASELINE, duration_s=300.0)
        assert result.confidence > 0.8

    def test_artifact_rate_degrades_confidence(self):
        gen = SyntheticPPIGenerator(persona=PersonaType.BASELINE, seed=42)
        ppi, ts = gen.generate(120.0, include_artifacts=False)

        r_clean    = compute_rsa(ppi, ts, artifact_rate=0.0)
        r_moderate = compute_rsa(ppi, ts, artifact_rate=0.3)
        assert r_clean.confidence > r_moderate.confidence


# ── Windowed RSA ──────────────────────────────────────────────────────────────

class TestWindowedRSA:

    def test_windowed_rsa_returns_list(self):
        gen = SyntheticPPIGenerator(persona=PersonaType.BASELINE, seed=42)
        ppi, ts = gen.generate(180.0, include_artifacts=False)
        windows = compute_windowed_rsa(ppi, ts, window_duration_s=60.0, step_s=10.0)
        assert isinstance(windows, list)
        assert len(windows) > 0

    def test_windowed_rsa_structure(self):
        gen = SyntheticPPIGenerator(persona=PersonaType.BASELINE, seed=42)
        ppi, ts = gen.generate(120.0, include_artifacts=False)
        windows = compute_windowed_rsa(ppi, ts, window_duration_s=60.0, step_s=30.0)

        for w in windows:
            assert "window_start_s" in w
            assert "rsa_power" in w
            assert "rsa_peak_freq_hz" in w
            assert "confidence" in w

    def test_windowed_rsa_empty_input(self):
        result = compute_windowed_rsa(np.array([]), np.array([]))
        assert result == []
