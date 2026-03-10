"""
tests/processing/test_synthetic_generator.py

Unit tests for processing/synthetic_generator.py

Validates:
  - Generator produces correct number of beats for given duration
  - PPI values within physiological range
  - RSA oscillation is present (RMSSD > 0 for non-constant signal)
  - Personas produce different RMSSD levels (as expected from params)
  - Session packet format is correct
  - Reproducibility with fixed seed
"""

import numpy as np
import pytest

from processing.synthetic_generator import (
    SyntheticPPIGenerator,
    PersonaType,
    PERSONA_PARAMS,
    generate_multi_persona_dataset,
)


# ── Duration correctness ───────────────────────────────────────────────────────

class TestDuration:

    @pytest.mark.parametrize("persona", list(PersonaType))
    def test_generated_duration_within_tolerance(self, persona):
        """Total stream duration should be within ±5% of requested."""
        target_s = 120.0
        gen = SyntheticPPIGenerator(persona=persona, seed=42)
        ppi, ts = gen.generate(duration_seconds=target_s)

        actual_duration = ts[-1] - ts[0]
        assert abs(actual_duration - target_s) < target_s * 0.05

    def test_baseline_60s_beat_count_approx(self):
        """BASELINE persona HR ~70bpm → ~70 beats/min."""
        gen = SyntheticPPIGenerator(persona=PersonaType.BASELINE, seed=42)
        ppi, ts = gen.generate(duration_seconds=60.0)
        # HR = 60000/860 ≈ 70 bpm
        assert 60 < len(ppi) < 85


# ── Physiological range ────────────────────────────────────────────────────────

class TestPhysiologicalRange:

    @pytest.mark.parametrize("persona", list(PersonaType))
    def test_all_ppi_in_range(self, persona):
        gen = SyntheticPPIGenerator(persona=persona, seed=42)
        ppi, _ = gen.generate(120.0)
        # After clipping, all should be within valid range
        assert np.all(ppi >= 300.0)
        assert np.all(ppi <= 2000.0)


# ── RSA signal content ─────────────────────────────────────────────────────────

class TestRSAContent:

    def test_baseline_rmssd_nonzero(self):
        gen = SyntheticPPIGenerator(persona=PersonaType.BASELINE, seed=42)
        ppi, _ = gen.generate(120.0, include_artifacts=False)
        diffs = np.diff(ppi)
        rmssd = float(np.sqrt(np.mean(diffs ** 2)))
        assert rmssd > 5.0  # Should have meaningful RSA oscillation

    def test_constant_ppi_would_give_zero_rmssd(self):
        """
        Sanity check: pure constant → 0 RMSSD.
        (Not from generator, just verifying our test logic.)
        """
        ppi = np.full(100, 800.0)
        diffs = np.diff(ppi)
        assert np.sqrt(np.mean(diffs ** 2)) == pytest.approx(0.0, abs=1e-6)


# ── Persona ordering ──────────────────────────────────────────────────────────

class TestPersonaOrdering:
    """
    Responder has highest RSA amplitude → highest RMSSD.
    Wire has lowest RSA amplitude → lowest RMSSD.
    (Without artifacts so artifact contamination doesn't affect ordering.)
    """

    def test_responder_rmssd_greater_than_wire(self):
        r_gen = SyntheticPPIGenerator(PersonaType.RESPONDER, seed=42)
        w_gen = SyntheticPPIGenerator(PersonaType.WIRE,      seed=42)

        r_ppi, _ = r_gen.generate(180.0, include_artifacts=False)
        w_ppi, _ = w_gen.generate(180.0, include_artifacts=False)

        r_rmssd = float(np.sqrt(np.mean(np.diff(r_ppi) ** 2)))
        w_rmssd = float(np.sqrt(np.mean(np.diff(w_ppi) ** 2)))

        assert r_rmssd > w_rmssd

    def test_mean_ppi_ordering_matches_params(self):
        """Mean PPI should be close to the configured PERSONA_PARAMS value."""
        for persona in PersonaType:
            expected = PERSONA_PARAMS[persona].mean_ppi_ms
            gen = SyntheticPPIGenerator(persona=persona, seed=42)
            ppi, _ = gen.generate(300.0, include_artifacts=False)
            actual_mean = float(np.mean(ppi))
            assert abs(actual_mean - expected) < expected * 0.05, (
                f"{persona}: expected ~{expected:.0f}ms, got {actual_mean:.0f}ms"
            )


# ── Reproducibility ────────────────────────────────────────────────────────────

class TestReproducibility:

    def test_same_seed_same_output(self):
        gen1 = SyntheticPPIGenerator(PersonaType.BASELINE, seed=42)
        gen2 = SyntheticPPIGenerator(PersonaType.BASELINE, seed=42)

        ppi1, ts1 = gen1.generate(60.0)
        ppi2, ts2 = gen2.generate(60.0)

        np.testing.assert_array_equal(ppi1, ppi2)
        np.testing.assert_array_equal(ts1, ts2)

    def test_different_seeds_different_output(self):
        gen1 = SyntheticPPIGenerator(PersonaType.BASELINE, seed=1)
        gen2 = SyntheticPPIGenerator(PersonaType.BASELINE, seed=2)

        ppi1, _ = gen1.generate(60.0)
        ppi2, _ = gen2.generate(60.0)
        # Very unlikely to be identical
        assert not np.array_equal(ppi1, ppi2)


# ── Session packet format ──────────────────────────────────────────────────────

class TestSessionPackets:

    def test_packet_keys(self):
        gen = SyntheticPPIGenerator(PersonaType.BASELINE, seed=42)
        packets = gen.generate_session_stream(30.0)
        assert len(packets) > 0
        for p in packets:
            assert "stream"   in p
            assert "context"  in p
            assert "ts"       in p
            assert "value"    in p
            assert "artifact" in p

    def test_packet_stream_value(self):
        gen = SyntheticPPIGenerator(PersonaType.BASELINE, seed=42)
        packets = gen.generate_session_stream(10.0)
        assert all(p["stream"] == "ppi" for p in packets)

    def test_packet_context_value(self):
        gen = SyntheticPPIGenerator(PersonaType.BASELINE, seed=42)
        packets = gen.generate_session_stream(10.0)
        assert all(p["context"] == "session" for p in packets)


# ── Multi-persona dataset ──────────────────────────────────────────────────────

class TestMultiPersonaDataset:

    def test_all_personas_present(self):
        dataset = generate_multi_persona_dataset(duration_seconds=60.0)
        for persona in PersonaType:
            assert persona.value in dataset

    def test_dataset_values_are_arrays(self):
        dataset = generate_multi_persona_dataset(duration_seconds=60.0)
        for _, (ppi, ts) in dataset.items():
            assert isinstance(ppi, np.ndarray)
            assert isinstance(ts, np.ndarray)
