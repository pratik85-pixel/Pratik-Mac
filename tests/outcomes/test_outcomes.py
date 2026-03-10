"""
tests/outcomes/test_outcomes.py

Tests for outcomes/session_outcomes.py and outcomes/level_gate.py.

Covers:
  Session outcomes
    - empty window list
    - all zone-1 windows (low quality)
    - mixed zones → correct composite score
    - pre/post RMSSD delta (positive and negative)
    - missing pre/post → no delta
    - personal_floor absent → delta_pct absent
    - session_score bounded 0.0–1.0
    - arc_completed propagates
    - arc detection logic (start low, rise, sustain)
    - is_scoreable and rmssd_improved helpers
    - aggregation helpers (coherence_avg_last_n, peak_avg, etc.)

  Level gate
    - stage 0 → not ready (not enough sessions)
    - stage 0 → ready
    - stage 1 → not ready (low coherence)
    - stage 1 → ready (all criteria met)
    - stage 2 → not ready (low arc fraction)
    - stage 2 → ready
    - stage 3 → not ready
    - stage 3 → ready
    - stage 4 → not ready (arc not shortening)
    - stage 4 → ready
    - stage 5 → nothing to advance, ready=False, blocking=[]
    - criteria_met keys are always correct
    - blocking is human-readable (non-empty string, no %)
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import pytest

from outcomes.session_outcomes import (
    SessionOutcome,
    arc_completion_fraction,
    arc_duration_trend,
    coherence_avg_last_n,
    coherence_peak_avg,
    compute_session_outcome,
    data_quality_avg,
    rmssd_delta_positive_fraction,
)
from outcomes.level_gate import LevelGateResult, check_level_gate
from processing.coherence_scorer import CoherenceResult
from processing.ppi_processor import PPIMetrics
from archetypes.scorer import NSHealthProfile


# ── Factories ──────────────────────────────────────────────────────────────────

def _cr(
    coherence: Optional[float],
    zone: Optional[int] = None,
    confidence: float = 0.9,
) -> CoherenceResult:
    """Build a CoherenceResult test fixture."""
    return CoherenceResult(
        coherence=coherence,
        zone=zone,
        rsa_power=None,
        total_power=None,
        confidence=confidence,
    )


def _ppi(rmssd_ms: Optional[float], confidence: float = 0.9) -> PPIMetrics:
    """Build a PPIMetrics test fixture."""
    return PPIMetrics(
        rmssd_ms=rmssd_ms,
        sdnn_ms=None,
        pnn50_pct=None,
        mean_hr_bpm=65.0,
        mean_ppi_ms=923.0,
        n_beats=120,
        confidence=confidence,
    )


def _profile(
    stage: int = 1,
    total_score: int = 50,
) -> NSHealthProfile:
    """Build a minimal NSHealthProfile test fixture."""
    return NSHealthProfile(
        total_score=total_score,
        stage=stage,
        stage_target=55,
        recovery_capacity=10,
        baseline_resilience=10,
        coherence_capacity=10,
        chrono_fit=10,
        load_management=10,
        primary_pattern="unclassified",
        amplifier_pattern=None,
        pattern_scores={},
        score_7d_delta=None,
        score_30d_delta=None,
        trajectory="stable",
        stage_focus=[],
        weeks_in_stage=0,
        overall_confidence=0.8,
        data_hours=10.0,
    )


def _outcome(
    coherence_avg: float = 0.50,
    coherence_peak: float = 0.70,
    time_in_zone_3_plus: float = 0.40,
    session_score: float = 0.55,
    rmssd_delta_ms: Optional[float] = 5.0,
    arc_completed: bool = False,
    arc_duration_hours: Optional[float] = None,
    data_quality: float = 0.90,
    session_date: Optional[date] = None,
) -> SessionOutcome:
    """Build a minimal SessionOutcome test fixture."""
    return SessionOutcome(
        session_id="test-id",
        session_date=session_date or date.today(),
        duration_minutes=20,
        session_type="full",
        coherence_avg=coherence_avg,
        coherence_peak=coherence_peak,
        time_in_zone_3_plus=time_in_zone_3_plus,
        session_score=session_score,
        pre_rmssd_ms=40.0,
        post_rmssd_ms=40.0 + (rmssd_delta_ms or 0.0),
        rmssd_delta_ms=rmssd_delta_ms,
        rmssd_delta_pct=None,
        arc_completed=arc_completed,
        arc_duration_hours=arc_duration_hours,
        morning_rmssd_ms=None,
        windows_valid=10,
        windows_total=10,
        data_quality=data_quality,
        notes=[],
    )


def _zone_for(coherence: float) -> int:
    """Mirror zone assignment logic for test fixtures."""
    if coherence >= 0.80:
        return 4
    if coherence >= 0.60:
        return 3
    if coherence >= 0.40:
        return 2
    return 1


def _windows(*coherences: float) -> list[CoherenceResult]:
    return [_cr(c, _zone_for(c)) for c in coherences]


# ─────────────────────────────────────────────────────────────────────────────
# SessionOutcome tests
# ─────────────────────────────────────────────────────────────────────────────

class TestComputeSessionOutcome:

    def test_empty_window_list_returns_none_metrics(self):
        o = compute_session_outcome([])
        assert o.coherence_avg is None
        assert o.coherence_peak is None
        assert o.time_in_zone_3_plus is None
        assert o.session_score is None
        assert o.data_quality == 0.0
        assert o.windows_total == 0
        assert o.windows_valid == 0
        assert "no_windows_recorded" in o.notes

    def test_all_zone1_windows(self):
        wins = _windows(0.20, 0.25, 0.30, 0.35)
        o = compute_session_outcome(wins)
        assert o.time_in_zone_3_plus == 0.0
        # session_score must be very low
        assert o.session_score is not None
        assert o.session_score < 0.30   # all low coherence

    def test_all_zone4_windows(self):
        wins = _windows(0.85, 0.90, 0.88, 0.92)
        o = compute_session_outcome(wins)
        assert o.time_in_zone_3_plus == 1.0
        assert o.session_score is not None
        assert o.session_score > 0.85

    def test_mixed_zones_composite_score(self):
        """Verify the weighted formula with predictable values."""
        # half zone 3+, half zone 1–2
        wins = _windows(0.70, 0.70, 0.30, 0.30)
        o = compute_session_outcome(wins)

        assert o.coherence_avg is not None
        assert o.coherence_peak is not None
        assert o.time_in_zone_3_plus is not None

        expected_avg  = (0.70 + 0.70 + 0.30 + 0.30) / 4   # 0.50
        expected_peak = 0.70
        expected_zone = 0.50    # 2 out of 4 windows in zone 3+

        expected_score = (
            expected_avg  * 0.40
            + expected_peak * 0.30
            + expected_zone * 0.30
        )
        assert abs(o.session_score - expected_score) < 1e-3

    def test_session_score_bounded_0_to_1(self):
        """Score must never exceed 1.0 even with all zone-4 windows."""
        wins = _windows(1.0, 1.0, 1.0, 1.0)
        o = compute_session_outcome(wins)
        assert 0.0 <= o.session_score <= 1.0

    def test_rmssd_delta_positive(self):
        pre  = _ppi(35.0)
        post = _ppi(48.0)
        o = compute_session_outcome(_windows(0.60, 0.65), pre_window_metrics=pre, post_window_metrics=post)
        assert o.rmssd_delta_ms == pytest.approx(13.0, abs=0.1)
        assert o.rmssd_delta_pct > 0.0
        assert o.rmssd_improved() is True
        assert "rmssd_improved" in o.notes

    def test_rmssd_delta_negative(self):
        pre  = _ppi(50.0)
        post = _ppi(40.0)
        o = compute_session_outcome(_windows(0.60), pre_window_metrics=pre, post_window_metrics=post)
        assert o.rmssd_delta_ms < 0.0
        assert o.rmssd_improved() is False
        assert "rmssd_declined" in o.notes

    def test_rmssd_delta_none_when_no_pre(self):
        o = compute_session_outcome(
            _windows(0.60, 0.70),
            pre_window_metrics=None,
            post_window_metrics=_ppi(45.0),
        )
        assert o.rmssd_delta_ms is None
        assert o.rmssd_delta_pct is None

    def test_rmssd_delta_none_when_no_post(self):
        o = compute_session_outcome(
            _windows(0.60, 0.70),
            pre_window_metrics=_ppi(40.0),
            post_window_metrics=None,
        )
        assert o.rmssd_delta_ms is None

    def test_invalid_ppi_metrics_treated_as_none(self):
        """PPIMetrics with confidence 0.0 should be treated as missing."""
        low_conf = _ppi(40.0, confidence=0.0)
        o = compute_session_outcome(
            _windows(0.60),
            pre_window_metrics=low_conf,
            post_window_metrics=_ppi(50.0),
        )
        assert o.rmssd_delta_ms is None

    def test_arc_completed_true_propagates(self):
        # arc: starts low, rises above 0.45 + 0.15 = 0.60, sustains 2 windows
        wins = _windows(0.30, 0.35, 0.65, 0.70, 0.72)
        o = compute_session_outcome(wins)
        assert o.arc_completed is True
        assert o.arc_duration_hours is not None
        assert "arc_completed" in o.notes

    def test_arc_not_completed_when_start_high(self):
        wins = _windows(0.55, 0.70, 0.75)   # start already above 0.45
        o = compute_session_outcome(wins)
        assert o.arc_completed is False

    def test_arc_not_completed_when_rise_insufficient(self):
        wins = _windows(0.30, 0.40, 0.42, 0.43)   # rise < 0.15
        o = compute_session_outcome(wins)
        assert o.arc_completed is False

    def test_arc_not_completed_when_not_sustained(self):
        # Rises above threshold but drops back before sustaining 2 windows
        wins = _windows(0.30, 0.70, 0.35, 0.36)
        o = compute_session_outcome(wins)
        assert o.arc_completed is False

    def test_data_quality_computed_correctly(self):
        good = [_cr(0.60, 3, confidence=0.9)] * 6
        bad  = [_cr(None, None, confidence=0.0)] * 4
        o = compute_session_outcome(good + bad)
        assert o.windows_total == 10
        assert o.windows_valid == 6
        assert o.data_quality == pytest.approx(0.6, abs=1e-4)

    def test_session_id_generated_if_not_provided(self):
        o = compute_session_outcome([])
        assert isinstance(o.session_id, str)
        assert len(o.session_id) > 0

    def test_session_id_used_if_provided(self):
        o = compute_session_outcome([], session_id="my-session-id")
        assert o.session_id == "my-session-id"

    def test_is_scoreable_requires_high_quality(self):
        """is_scoreable only true when data_quality >= 0.5 and session_score exists."""
        # Enough valid windows
        wins = [_cr(0.60, 3)] * 6 + [_cr(None, None, confidence=0.0)] * 4
        o = compute_session_outcome(wins)
        assert o.is_scoreable() is True

        # Too many invalid
        wins2 = [_cr(0.60, 3)] * 3 + [_cr(None, None, confidence=0.0)] * 8
        o2 = compute_session_outcome(wins2)
        assert o2.is_scoreable() is False

    def test_morning_rmssd_ms_stored_as_context(self):
        o = compute_session_outcome([], morning_rmssd_ms=55.0)
        assert o.morning_rmssd_ms == 55.0


# ─────────────────────────────────────────────────────────────────────────────
# Aggregation helper tests
# ─────────────────────────────────────────────────────────────────────────────

class TestAggregationHelpers:

    def _outcomes(self, n: int, *, coh: float = 0.50) -> list[SessionOutcome]:
        return [_outcome(coherence_avg=coh, coherence_peak=coh + 0.10) for _ in range(n)]

    def test_coherence_avg_last_n_returns_last_3(self):
        history = [
            _outcome(coherence_avg=0.40),
            _outcome(coherence_avg=0.50),
            _outcome(coherence_avg=0.60),
            _outcome(coherence_avg=0.70),
        ]
        result = coherence_avg_last_n(history, 3)
        # last 3: 0.50, 0.60, 0.70 → mean = 0.60
        assert result == pytest.approx(0.60, abs=1e-4)

    def test_coherence_avg_last_n_empty(self):
        assert coherence_avg_last_n([], 3) is None

    def test_coherence_avg_last_n_excludes_none_values(self):
        # Outcome with coherence_avg=None should be excluded
        bad = SessionOutcome(
            session_id="x", session_date=date.today(), duration_minutes=10,
            session_type="full", coherence_avg=None, coherence_peak=None,
            time_in_zone_3_plus=None, session_score=None,
            pre_rmssd_ms=None, post_rmssd_ms=None,
            rmssd_delta_ms=None, rmssd_delta_pct=None,
            arc_completed=False, arc_duration_hours=None,
            morning_rmssd_ms=None, windows_valid=0, windows_total=0,
            data_quality=0.0,
        )
        good = _outcome(coherence_avg=0.50)
        result = coherence_avg_last_n([bad, good], 3)
        assert result == pytest.approx(0.50, abs=1e-4)

    def test_coherence_peak_avg(self):
        history = [
            _outcome(coherence_peak=0.70),
            _outcome(coherence_peak=0.80),
            _outcome(coherence_peak=0.90),
        ]
        result = coherence_peak_avg(history)
        assert result == pytest.approx(0.80, abs=1e-4)

    def test_coherence_peak_avg_empty(self):
        assert coherence_peak_avg([]) is None

    def test_rmssd_delta_positive_fraction(self):
        history = [
            _outcome(rmssd_delta_ms=5.0),
            _outcome(rmssd_delta_ms=-3.0),
            _outcome(rmssd_delta_ms=8.0),
            _outcome(rmssd_delta_ms=2.0),
        ]
        result = rmssd_delta_positive_fraction(history)
        assert result == pytest.approx(0.75, abs=1e-4)

    def test_rmssd_delta_positive_fraction_no_deltas(self):
        """Outcomes with no delta recorded return 0.0."""
        history = [
            _outcome(rmssd_delta_ms=None),
            _outcome(rmssd_delta_ms=None),
        ]
        result = rmssd_delta_positive_fraction(history)
        assert result == 0.0

    def test_arc_completion_fraction(self):
        history = [
            _outcome(arc_completed=True),
            _outcome(arc_completed=False),
            _outcome(arc_completed=True),
            _outcome(arc_completed=False),
        ]
        assert arc_completion_fraction(history) == pytest.approx(0.5, abs=1e-4)

    def test_arc_completion_fraction_empty(self):
        assert arc_completion_fraction([]) == 0.0

    def test_data_quality_avg(self):
        history = [
            _outcome(data_quality=0.80),
            _outcome(data_quality=0.60),
            _outcome(data_quality=1.00),
        ]
        result = data_quality_avg(history)
        assert result == pytest.approx(0.80, abs=1e-4)

    def test_arc_duration_trend_shortening(self):
        # First 6 sessions take 1.0 hour; last 3 take 0.5 hours
        baseline = [_outcome(arc_completed=True, arc_duration_hours=1.0)] * 6
        recent   = [_outcome(arc_completed=True, arc_duration_hours=0.5)] * 3
        assert arc_duration_trend(baseline + recent) == "shortening"

    def test_arc_duration_trend_lengthening(self):
        baseline = [_outcome(arc_completed=True, arc_duration_hours=0.5)] * 6
        recent   = [_outcome(arc_completed=True, arc_duration_hours=1.5)] * 3
        assert arc_duration_trend(baseline + recent) == "lengthening"

    def test_arc_duration_trend_stable(self):
        baseline = [_outcome(arc_completed=True, arc_duration_hours=1.0)] * 6
        recent   = [_outcome(arc_completed=True, arc_duration_hours=1.0)] * 3
        assert arc_duration_trend(baseline + recent) == "stable"

    def test_arc_duration_trend_insufficient_data(self):
        history = [_outcome(arc_completed=True, arc_duration_hours=1.0)] * 5
        assert arc_duration_trend(history) == "insufficient_data"


# ─────────────────────────────────────────────────────────────────────────────
# Level gate tests
# ─────────────────────────────────────────────────────────────────────────────

class TestLevelGate:

    # ── Stage 5: no advancement ───────────────────────────────────────────────

    def test_stage_5_returns_not_ready_with_empty_blocking(self):
        result = check_level_gate(_profile(stage=5, total_score=95), [])
        assert result.ready is False
        assert result.blocking == []
        assert result.next_stage is None

    # ── Stage 0 → 1 ──────────────────────────────────────────────────────────

    def test_gate_0_to_1_not_ready_insufficient_sessions(self):
        result = check_level_gate(_profile(stage=0, total_score=40), [])
        assert result.ready is False
        assert result.next_stage == 1
        assert result.criteria_met["sufficient_sessions"] is False
        assert any("session" in m.lower() for m in result.blocking)

    def test_gate_0_to_1_not_ready_low_score(self):
        history = [_outcome(data_quality=0.80)] * 2
        result = check_level_gate(_profile(stage=0, total_score=30), history)
        assert result.ready is False
        assert result.criteria_met["total_score_35"] is False

    def test_gate_0_to_1_not_ready_low_data_quality(self):
        history = [_outcome(data_quality=0.30)] * 2
        result = check_level_gate(_profile(stage=0, total_score=40), history)
        assert result.ready is False
        assert result.criteria_met["data_quality_avg_0.50"] is False

    def test_gate_0_to_1_ready(self):
        history = [_outcome(data_quality=0.80)] * 2
        result = check_level_gate(_profile(stage=0, total_score=40), history)
        assert result.ready is True
        assert result.next_stage == 1
        assert result.blocking == []

    # ── Stage 1 → 2 ──────────────────────────────────────────────────────────

    def test_gate_1_to_2_not_ready_insufficient_sessions(self):
        history = [_outcome(coherence_avg=0.50)] * 3
        result = check_level_gate(_profile(stage=1, total_score=60), history)
        assert result.ready is False
        assert result.criteria_met["sufficient_sessions"] is False

    def test_gate_1_to_2_not_ready_low_coherence(self):
        history = [_outcome(coherence_avg=0.30, rmssd_delta_ms=5.0)] * 6
        result = check_level_gate(_profile(stage=1, total_score=60), history)
        assert result.ready is False
        assert result.criteria_met["coherence_avg_last3_0.40"] is False

    def test_gate_1_to_2_not_ready_low_rmssd_fraction(self):
        history = (
            [_outcome(coherence_avg=0.45, rmssd_delta_ms=5.0)] * 2
            + [_outcome(coherence_avg=0.45, rmssd_delta_ms=-5.0)] * 4
        )
        result = check_level_gate(_profile(stage=1, total_score=60), history)
        assert result.criteria_met["rmssd_delta_positive_50pct"] is False

    def test_gate_1_to_2_ready(self):
        history = [_outcome(coherence_avg=0.50, rmssd_delta_ms=5.0)] * 6
        result = check_level_gate(_profile(stage=1, total_score=60), history)
        assert result.ready is True
        assert result.next_stage == 2

    # ── Stage 2 → 3 ──────────────────────────────────────────────────────────

    def test_gate_2_to_3_not_ready_insufficient_sessions(self):
        history = [_outcome(coherence_avg=0.60, arc_completed=True)] * 8
        result = check_level_gate(_profile(stage=2, total_score=75), history)
        assert result.ready is False

    def test_gate_2_to_3_not_ready_low_arc_fraction(self):
        history = [_outcome(coherence_avg=0.60, arc_completed=False)] * 12
        result = check_level_gate(_profile(stage=2, total_score=75), history)
        assert result.criteria_met["arc_completed_50pct"] is False

    def test_gate_2_to_3_ready(self):
        history = [_outcome(coherence_avg=0.60, arc_completed=True)] * 12
        result = check_level_gate(_profile(stage=2, total_score=75), history)
        assert result.ready is True
        assert result.next_stage == 3

    # ── Stage 3 → 4 ──────────────────────────────────────────────────────────

    def test_gate_3_to_4_not_ready_low_peak_avg(self):
        history = [_outcome(coherence_peak=0.65, rmssd_delta_ms=5.0)] * 18
        result = check_level_gate(_profile(stage=3, total_score=82), history)
        assert result.criteria_met["coherence_peak_avg_0.70"] is False

    def test_gate_3_to_4_ready(self):
        history = [_outcome(coherence_peak=0.72, rmssd_delta_ms=5.0)] * 18
        result = check_level_gate(_profile(stage=3, total_score=82), history)
        assert result.ready is True
        assert result.next_stage == 4

    # ── Stage 4 → 5 ──────────────────────────────────────────────────────────

    def test_gate_4_to_5_not_ready_arc_not_shortening(self):
        history = [
            _outcome(coherence_peak=0.82, rmssd_delta_ms=5.0,
                     arc_completed=True, arc_duration_hours=1.0)
        ] * 24
        result = check_level_gate(_profile(stage=4, total_score=92), history)
        # arc trend = "stable", not "shortening"
        assert result.criteria_met["arc_duration_shortening"] is False
        assert result.ready is False

    def test_gate_4_to_5_ready(self):
        # baseline: 6 sessions at 1.0h arc; filler sessions; recent 3 at 0.5h
        baseline  = [_outcome(coherence_peak=0.82, rmssd_delta_ms=5.0, arc_completed=True, arc_duration_hours=1.0)] * 6
        middle    = [_outcome(coherence_peak=0.82, rmssd_delta_ms=5.0, arc_completed=True, arc_duration_hours=0.8)] * 15
        recent    = [_outcome(coherence_peak=0.82, rmssd_delta_ms=5.0, arc_completed=True, arc_duration_hours=0.5)] * 3
        history = baseline + middle + recent
        result = check_level_gate(_profile(stage=4, total_score=92), history)
        assert result.criteria_met["arc_duration_shortening"] is True
        assert result.ready is True
        assert result.next_stage == 5

    # ── Structural / cross-cutting ────────────────────────────────────────────

    def test_criteria_met_keys_are_present(self):
        """criteria_met should always have at least one key for stages 0–4."""
        for stage in range(5):
            score = [35, 55, 70, 80, 90][stage]
            result = check_level_gate(_profile(stage=stage, total_score=score), [])
            assert len(result.criteria_met) >= 3, f"stage {stage} has no criteria"

    def test_blocking_messages_are_plain_english(self):
        """Each blocking string should be a non-empty human sentence."""
        result = check_level_gate(_profile(stage=1, total_score=30), [])
        for msg in result.blocking:
            assert isinstance(msg, str)
            assert len(msg) > 10

    def test_ready_implies_blocking_empty(self):
        """If ready=True, blocking must be empty."""
        history = [_outcome(coherence_avg=0.50, rmssd_delta_ms=5.0)] * 6
        result = check_level_gate(_profile(stage=1, total_score=60), history)
        if result.ready:
            assert result.blocking == []

    def test_not_ready_implies_blocking_nonempty_when_criteria_exist(self):
        """If ready=False and stage < 5, at least one criterion should be unmet."""
        result = check_level_gate(_profile(stage=0, total_score=10), [])
        assert result.ready is False
        assert len(result.blocking) >= 1
