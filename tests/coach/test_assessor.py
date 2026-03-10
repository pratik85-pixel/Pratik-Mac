"""
tests/coach/test_assessor.py

Unit tests for coach/assessor.py — 3-gate level advancement system.
"""

import pytest

from coach.assessor import (
    ADHERENCE_THRESHOLD,
    ADHERENCE_WINDOW,
    MIN_SESSION_FLOOR,
    READINESS_IMPROVEMENT_PTS,
    SESSION_QUALITY_THRESHOLD,
    ConversationSignal,
    DeviationRecord,
    ReadinessRecord,
    SessionRecord,
    UserAssessment,
    assess_user,
    evaluate_level_gate,
    _gate_1_adherence,
    _gate_2_readiness,
    _gate_3_quality,
    _classify_learning_state,
    _find_recurring_deviations,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _sessions(prescribed: int, completed: int, score: float = 0.5) -> list[SessionRecord]:
    """Build a list of session records."""
    sessions = []
    for i in range(prescribed):
        is_completed = i < completed
        sessions.append(SessionRecord(
            session_id=f"s{i}",
            session_score=score if is_completed else None,
            was_prescribed=True,
            completed=is_completed,
        ))
    return sessions


def _readiness(values: list[float]) -> list[ReadinessRecord]:
    return [ReadinessRecord(date_index=i, readiness=v) for i, v in enumerate(values)]


# ── Gate 1 — Adherence ────────────────────────────────────────────────────────

class TestGate1Adherence:
    def test_60_pct_passes(self):
        sessions = _sessions(10, 6)
        gate = _gate_1_adherence(sessions)
        assert gate.passed is True
        assert gate.value == pytest.approx(0.6, abs=0.01)

    def test_50_pct_fails(self):
        sessions = _sessions(10, 5)
        gate = _gate_1_adherence(sessions)
        assert gate.passed is False

    def test_100_pct_passes(self):
        sessions = _sessions(10, 10)
        gate = _gate_1_adherence(sessions)
        assert gate.passed is True

    def test_no_prescribed_sessions_fails(self):
        gate = _gate_1_adherence([])
        assert gate.passed is False

    def test_only_last_10_considered(self):
        # 20 sessions total: first 10 all missed, last 10 all completed
        first_10 = _sessions(10, 0)
        last_10 = _sessions(10, 10)
        gate = _gate_1_adherence(first_10 + last_10)
        assert gate.passed is True

    def test_non_prescribed_sessions_excluded(self):
        sessions = _sessions(7, 5)
        # Add non-prescribed sessions
        sessions += [SessionRecord(session_id="x", session_score=0.8,
                                   was_prescribed=False, completed=True)] * 5
        gate = _gate_1_adherence(sessions)
        # Only 7 prescribed — 5/7 ~ 71% — should pass
        assert gate.passed is True


# ── Gate 2 — Readiness trend ──────────────────────────────────────────────────

class TestGate2Readiness:
    def test_improving_5_pts_passes(self):
        # Prior 14 days avg=50, recent 14 days avg=56
        values = [50.0] * 14 + [56.0] * 14
        gate = _gate_2_readiness(_readiness(values))
        assert gate.passed is True
        assert gate.value == pytest.approx(6.0, abs=0.1)

    def test_no_improvement_fails(self):
        values = [50.0] * 28
        gate = _gate_2_readiness(_readiness(values))
        assert gate.passed is False

    def test_decline_fails(self):
        values = [60.0] * 14 + [50.0] * 14
        gate = _gate_2_readiness(_readiness(values))
        assert gate.passed is False

    def test_less_than_28_days_fails(self):
        gate = _gate_2_readiness(_readiness([55.0] * 20))
        assert gate.passed is False

    def test_exactly_5_pts_improvement_passes(self):
        values = [50.0] * 14 + [55.0] * 14
        gate = _gate_2_readiness(_readiness(values))
        assert gate.passed is True


# ── Gate 3 — Session quality (soft) ──────────────────────────────────────────

class TestGate3Quality:
    def test_above_threshold_passes(self):
        sessions = _sessions(5, 5, score=50.0)   # 50/100 = 0.50 > 0.25
        gate = _gate_3_quality(sessions)
        assert gate.passed is True

    def test_below_threshold_fails_but_soft(self):
        sessions = _sessions(5, 5, score=15.0)   # 0.15 < 0.25
        gate = _gate_3_quality(sessions)
        assert gate.passed is False

    def test_no_scored_sessions_passes_soft(self):
        sessions = [SessionRecord(session_id="x", session_score=None,
                                  was_prescribed=True, completed=True)]
        gate = _gate_3_quality(sessions)
        assert gate.passed is True   # no data → not penalised

    def test_score_normalisation_0_to_1(self):
        # Session score of 1.0 (already 0–1 range)
        sessions = [SessionRecord(session_id=f"s{i}", session_score=0.8,
                                  was_prescribed=True, completed=True)
                    for i in range(3)]
        gate = _gate_3_quality(sessions)
        assert gate.passed is True


# ── Gate: full level gate ─────────────────────────────────────────────────────

class TestEvaluateLevelGate:
    def test_all_gates_pass_ready(self):
        sessions = _sessions(10, 7, score=50.0)
        readiness = [50.0] * 14 + [56.0] * 14
        result = evaluate_level_gate(
            current_stage=1,
            session_records=sessions + _sessions(6, 6),  # meet floor of 6
            readiness_records=_readiness(readiness),
        )
        # Floor is 6 for 1→2
        assert result.gate_1_adherence.passed is True
        assert result.gate_2_readiness.passed is True
        # Ready only if floor also met

    def test_stage_5_not_ready(self):
        result = evaluate_level_gate(
            current_stage=5,
            session_records=_sessions(30, 30),
            readiness_records=_readiness([80.0] * 28),
        )
        assert result.ready is False
        assert result.next_stage is None

    def test_below_floor_not_ready(self):
        # Stage 0→1 needs 2 sessions min
        result = evaluate_level_gate(
            current_stage=0,
            session_records=_sessions(1, 1, score=50.0),
            readiness_records=_readiness([50.0] * 28),
        )
        assert result.floor_met is False
        assert result.ready is False

    def test_conversation_suppression_blocks_ready(self):
        sessions = _sessions(10, 7, score=50.0) + _sessions(6, 6)
        readiness = [50.0] * 14 + [57.0] * 14
        signals = [ConversationSignal(signal_label="I'm overwhelmed", days_ago=2)]
        result = evaluate_level_gate(
            current_stage=1,
            session_records=sessions,
            readiness_records=_readiness(readiness),
            conversation_signals=signals,
        )
        assert result.suppressed_by == ["I'm overwhelmed"]
        assert result.ready is False

    def test_conversation_signal_too_old_not_suppressed(self):
        sessions = _sessions(10, 8, score=60.0) + _sessions(6, 6)
        readiness = [50.0] * 14 + [57.0] * 14
        signals = [ConversationSignal(signal_label="overwhelmed", days_ago=10)]
        result = evaluate_level_gate(
            current_stage=1,
            session_records=sessions,
            readiness_records=_readiness(readiness),
            conversation_signals=signals,
        )
        assert result.suppressed_by == []


# ── Learning state ─────────────────────────────────────────────────────────────

class TestLearningState:
    def test_improving(self):
        values = [50.0] * 7 + [56.0] * 7
        state = _classify_learning_state(_readiness(values))
        assert state == "improving"

    def test_declining(self):
        values = [60.0] * 7 + [54.0] * 7
        state = _classify_learning_state(_readiness(values))
        assert state == "declining"

    def test_plateaued(self):
        values = [55.0] * 14
        state = _classify_learning_state(_readiness(values))
        assert state == "plateaued"

    def test_stabilizing(self):
        values = [52.0, 54.0, 53.0, 55.0, 52.0, 54.0, 53.0]
        state = _classify_learning_state(_readiness(values))
        # Small deltas — should be stabilizing or plateaued
        assert state in ("stabilizing", "plateaued")

    def test_insufficient_data_stabilizing(self):
        state = _classify_learning_state(_readiness([50.0] * 4))
        assert state == "stabilizing"


# ── Deviation analysis ────────────────────────────────────────────────────────

class TestDeviationAnalysis:
    def test_recurring_time_constraint(self):
        devs = [DeviationRecord("coherence_breathing", "must_do", "time_constraint")] * 4
        result = _find_recurring_deviations(devs)
        assert "time_constraint" in result

    def test_below_threshold_not_flagged(self):
        devs = [DeviationRecord("coherence_breathing", "must_do", "time_constraint")] * 2
        result = _find_recurring_deviations(devs)
        assert "time_constraint" not in result

    def test_none_reason_ignored(self):
        devs = [DeviationRecord("coherence_breathing", "must_do", None)] * 5
        result = _find_recurring_deviations(devs)
        assert result == []


# ── Full user assessment ──────────────────────────────────────────────────────

class TestAssessUser:
    def test_returns_user_assessment(self):
        sessions = _sessions(10, 7, score=50.0)
        readiness = _readiness([50.0] * 28)
        result = assess_user(
            current_stage=0,
            session_records=sessions,
            readiness_records=readiness,
        )
        assert isinstance(result, UserAssessment)
        assert isinstance(result.learning_state, str)
        assert isinstance(result.summary_note, str)

    def test_sport_stressors_passed_through(self):
        sessions = _sessions(5, 3)
        readiness = _readiness([50.0] * 14)
        result = assess_user(
            current_stage=0,
            session_records=sessions,
            readiness_records=readiness,
            sport_stressors=["sports", "running"],
        )
        assert "sports" in result.sport_stressors
        assert "running" in result.sport_stressors
