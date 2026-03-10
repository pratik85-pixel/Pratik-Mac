"""
tests/processing/test_coherence_scorer.py

Unit tests for processing/coherence_scorer.py

Validates:
  - Coherence in [0, 1]
  - Zone assignment matches ScoringConfig thresholds
  - Responder persona coherence > Wire persona coherence
  - Session score computation
  - Zone time accounting
"""

import numpy as np
import pytest

from processing.synthetic_generator import SyntheticPPIGenerator, PersonaType
from processing.coherence_scorer import (
    compute_coherence,
    compute_session_coherence_avg,
    compute_zone_time_seconds,
    compute_session_score,
    CoherenceResult,
)
from config import CONFIG


def get_persona_coherence(persona: PersonaType, duration_s: float = 180.0):
    gen = SyntheticPPIGenerator(persona=persona, seed=42)
    ppi, ts = gen.generate(duration_seconds=duration_s, include_artifacts=False)
    return compute_coherence(ppi, ts, artifact_rate=0.0)


# ── Basic validity ─────────────────────────────────────────────────────────────

class TestCoherenceBasic:

    def test_baseline_coherence_is_valid(self):
        result = get_persona_coherence(PersonaType.BASELINE, 180.0)
        assert result.is_valid()

    def test_coherence_in_unit_range(self):
        result = get_persona_coherence(PersonaType.BASELINE, 180.0)
        assert 0.0 <= result.coherence <= 1.0

    def test_zone_is_1_to_4(self):
        result = get_persona_coherence(PersonaType.BASELINE, 180.0)
        assert result.zone in (1, 2, 3, 4)

    def test_insufficient_data_returns_invalid(self):
        ppi = np.full(5, 800.0)
        ts  = np.linspace(0.0, 4.0, 5)
        result = compute_coherence(ppi, ts)
        assert not result.is_valid()


# ── Persona ordering ──────────────────────────────────────────────────────────

class TestCoherenceOrdering:
    """
    Responder: high RSA amplitude → high coherence power concentration.
    Wire: low RSA → more scattered power.
    """

    def test_responder_coherence_greater_than_wire(self):
        r_resp = get_persona_coherence(PersonaType.RESPONDER, 240.0)
        r_wire = get_persona_coherence(PersonaType.WIRE,      240.0)
        assert r_resp.is_valid()
        assert r_wire.is_valid()
        assert r_resp.coherence > r_wire.coherence


# ── Zone assignment ────────────────────────────────────────────────────────────

class TestZoneAssignment:

    def test_zone_1_threshold(self):
        sc = CONFIG.scoring
        # Coherence just below zone 2 threshold → zone 1
        result = CoherenceResult(
            coherence=sc.ZONE_2_MIN - 0.01,
            zone=None, rsa_power=0.1, total_power=0.4, confidence=0.9
        )
        from processing.coherence_scorer import _assign_zone
        assert _assign_zone(sc.ZONE_2_MIN - 0.01) == 1

    def test_zone_2_threshold(self):
        sc = CONFIG.scoring
        from processing.coherence_scorer import _assign_zone
        assert _assign_zone(sc.ZONE_2_MIN) == 2

    def test_zone_3_threshold(self):
        sc = CONFIG.scoring
        from processing.coherence_scorer import _assign_zone
        assert _assign_zone(sc.ZONE_3_MIN) == 3

    def test_zone_4_threshold(self):
        sc = CONFIG.scoring
        from processing.coherence_scorer import _assign_zone
        assert _assign_zone(sc.ZONE_4_MIN) == 4


# ── Session aggregation ────────────────────────────────────────────────────────

def make_window_results(zones: list, confidence: float = 0.9) -> list[CoherenceResult]:
    sc = CONFIG.scoring
    zone_coherence = {
        1: sc.ZONE_1_MIN + 0.05,
        2: sc.ZONE_2_MIN + 0.05,
        3: sc.ZONE_3_MIN + 0.05,
        4: sc.ZONE_4_MIN + 0.05,
    }
    return [
        CoherenceResult(
            coherence=zone_coherence[z], zone=z,
            rsa_power=0.1, total_power=0.2, confidence=confidence
        )
        for z in zones
    ]


class TestSessionAggregation:

    def test_session_coherence_avg(self):
        windows = make_window_results([2, 3, 4])
        sc = CONFIG.scoring
        expected_avg = np.mean([
            sc.ZONE_2_MIN + 0.05,
            sc.ZONE_3_MIN + 0.05,
            sc.ZONE_4_MIN + 0.05,
        ])
        avg = compute_session_coherence_avg(windows)
        assert avg == pytest.approx(expected_avg, abs=1e-4)

    def test_session_coherence_avg_none_when_empty(self):
        assert compute_session_coherence_avg([]) is None

    def test_session_coherence_avg_excludes_low_confidence(self):
        high_confidence = make_window_results([4], confidence=0.9)
        low_confidence  = make_window_results([1], confidence=0.1)
        avg = compute_session_coherence_avg(high_confidence + low_confidence)
        # Only zone 4 window should be included
        sc = CONFIG.scoring
        assert avg == pytest.approx(sc.ZONE_4_MIN + 0.05, abs=1e-4)

    def test_zone_time_seconds(self):
        windows = make_window_results([2, 2, 3, 4])
        zone_time = compute_zone_time_seconds(windows, window_duration_s=10.0)
        assert zone_time[2] == pytest.approx(20.0)
        assert zone_time[3] == pytest.approx(10.0)
        assert zone_time[4] == pytest.approx(10.0)

    def test_session_score_all_zone4(self):
        windows = make_window_results([4] * 20)
        score = compute_session_score(windows, window_duration_s=10.0)
        assert score is not None
        # All time in zone 4 → maximum score
        assert score > 90.0

    def test_session_score_all_zone1(self):
        windows = make_window_results([1] * 20)
        score = compute_session_score(windows, window_duration_s=10.0)
        assert score is not None
        assert score < 30.0

    def test_session_score_none_when_empty(self):
        assert compute_session_score([]) is None
