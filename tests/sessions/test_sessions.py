"""
tests/sessions/test_sessions.py

Tests for the sessions/ layer:
  - practice_registry
  - pacer_config
  - step_down_controller
  - session_prescriber
  - session_schema
"""

from __future__ import annotations

from typing import Optional

import pytest

from sessions.practice_registry import (
    VALID_PRACTICE_TYPES,
    VALID_ATTENTION_ANCHORS,
    get_practice,
    is_available_at_stage,
    practices_for_stage,
)
from sessions.pacer_config import PacerConfig, build_pacer_config
from sessions.step_down_controller import StepDownController, GateEvaluation
from sessions.session_prescriber import (
    PRF_UNKNOWN, PRF_FOUND, PRF_CONFIRMED,
    prescribe_session,
)
from sessions.session_schema import PracticeSession
from processing.breath_rate_estimator import BreathRateEstimate
from processing.coherence_scorer import CoherenceResult


# ── Fixtures ───────────────────────────────────────────────────────────────────

def _cr(coherence: float, confidence: float = 0.9) -> CoherenceResult:
    zone = 4 if coherence >= 0.80 else 3 if coherence >= 0.60 else 2 if coherence >= 0.40 else 1
    return CoherenceResult(coherence=coherence, zone=zone,
                           rsa_power=None, total_power=None, confidence=confidence)

def _cr_invalid() -> CoherenceResult:
    return CoherenceResult(coherence=None, zone=None,
                           rsa_power=None, total_power=None, confidence=0.0)

def _bpm(bpm: float, confidence: float = 0.9) -> BreathRateEstimate:
    return BreathRateEstimate(bpm=bpm, confidence=confidence, n_cycles=4)

def _bpm_invalid() -> BreathRateEstimate:
    return BreathRateEstimate(bpm=None, confidence=0.0, n_cycles=0)


# ─────────────────────────────────────────────────────────────────────────────
# Practice registry
# ─────────────────────────────────────────────────────────────────────────────

class TestPracticeRegistry:

    def test_all_practice_types_in_valid_set(self):
        for pt in VALID_PRACTICE_TYPES:
            desc = get_practice(pt)
            assert desc.practice_type == pt

    def test_get_practice_unknown_raises(self):
        with pytest.raises(KeyError):
            get_practice("not_a_practice")

    def test_ring_entrainment_stage_0_only(self):
        desc = get_practice("ring_entrainment")
        assert desc.min_stage == 0
        assert desc.max_stage == 0

    def test_resonance_hold_available_all_stages(self):
        desc = get_practice("resonance_hold")
        for stage in range(1, 6):
            assert is_available_at_stage("resonance_hold", stage)

    def test_resonance_hold_not_available_stage_0(self):
        assert is_available_at_stage("resonance_hold", 0) is False

    def test_silent_meditation_stage_4_plus_only(self):
        for stage in range(4, 6):
            assert is_available_at_stage("silent_meditation", stage)
        for stage in range(0, 4):
            assert is_available_at_stage("silent_meditation", stage) is False

    def test_practices_for_stage_0_includes_entrainment(self):
        stage0 = practices_for_stage(0)
        types  = {p.practice_type for p in stage0}
        assert "ring_entrainment" in types
        assert "prf_discovery" in types
        assert "silent_meditation" not in types

    def test_practices_for_stage_4_includes_silent_meditation(self):
        stage4 = practices_for_stage(4)
        types  = {p.practice_type for p in stage4}
        assert "silent_meditation" in types

    def test_box_breathing_high_stress_flag(self):
        desc = get_practice("box_breathing")
        assert desc.prescribed_on_high_stress is True

    def test_plexus_practices_allow_anchor(self):
        assert get_practice("plexus_hold").attention_anchor_allowed is True
        assert get_practice("plexus_step_down").attention_anchor_allowed is True

    def test_resonance_hold_does_not_use_step_down(self):
        assert get_practice("resonance_hold").step_down is False

    def test_prf_discovery_uses_step_down(self):
        assert get_practice("prf_discovery").step_down is True

    def test_silent_meditation_no_pacer(self):
        assert get_practice("silent_meditation").pacer_required is False

    def test_valid_attention_anchors_set(self):
        assert "heart" in VALID_ATTENTION_ANCHORS
        assert "belly" in VALID_ATTENTION_ANCHORS
        assert "brow" in VALID_ATTENTION_ANCHORS

    def test_is_available_unknown_practice_returns_false(self):
        assert is_available_at_stage("not_real", 2) is False


# ─────────────────────────────────────────────────────────────────────────────
# PacerConfig
# ─────────────────────────────────────────────────────────────────────────────

class TestPacerConfig:

    def test_cycle_duration_sums_correctly(self):
        pacer = build_pacer_config("resonance_hold", target_bpm=6.0)
        expected = 60.0 / 6.0  # 10 seconds
        assert abs(pacer.cycle_duration_sec - expected) < 0.1

    def test_implied_bpm_close_to_target(self):
        pacer = build_pacer_config("resonance_hold", target_bpm=6.0)
        assert abs(pacer.implied_bpm - 6.0) < 0.1

    def test_box_breathing_equal_phases(self):
        pacer = build_pacer_config("box_breathing", target_bpm=3.75)
        assert abs(pacer.inhale_sec - pacer.exhale_sec) < 0.1
        assert abs(pacer.pause_after_inhale_sec - pacer.pause_after_exhale_sec) < 0.1
        assert abs(pacer.inhale_sec - pacer.pause_after_inhale_sec) < 0.1

    def test_step_down_enabled_flag(self):
        pacer = build_pacer_config(
            "prf_discovery", target_bpm=12.0,
            step_down_enabled=True, step_down_from_bpm=12.0, step_down_to_bpm=6.0,
        )
        assert pacer.step_down_enabled is True
        assert pacer.step_down_from_bpm == 12.0
        assert pacer.step_down_to_bpm == 6.0

    def test_stepped_down_reduces_bpm(self):
        pacer = build_pacer_config(
            "prf_discovery", target_bpm=10.0,
            step_down_enabled=True, step_down_from_bpm=12.0, step_down_to_bpm=6.0,
            step_down_increment=0.5,
        )
        new_pacer = pacer.stepped_down()
        assert new_pacer.target_bpm == pytest.approx(9.5, abs=0.05)

    def test_at_floor_true_when_at_stop_bpm(self):
        pacer = build_pacer_config(
            "prf_discovery", target_bpm=6.0,
            step_down_enabled=True, step_down_to_bpm=6.0,
        )
        assert pacer.at_floor() is True

    def test_at_floor_false_above_stop_bpm(self):
        pacer = build_pacer_config(
            "prf_discovery", target_bpm=8.0,
            step_down_enabled=True, step_down_to_bpm=6.0,
        )
        assert pacer.at_floor() is False

    def test_attention_anchor_stored(self):
        pacer = build_pacer_config("plexus_hold", target_bpm=6.0, attention_anchor="heart")
        assert pacer.attention_anchor == "heart"

    def test_custom_ratio_override(self):
        """Custom ratios should produce different phase durations."""
        default_pacer = build_pacer_config("resonance_hold", target_bpm=6.0)
        custom_pacer  = build_pacer_config(
            "resonance_hold", target_bpm=6.0,
            inhale_frac=0.40, pause_inhale_frac=0.10,
            exhale_frac=0.40, pause_exhale_frac=0.10,
        )
        cycle = 60.0 / 6.0
        assert abs(custom_pacer.inhale_sec - 0.40 * cycle) < 0.05
        assert abs(default_pacer.inhale_sec - 0.45 * cycle) < 0.05


# ─────────────────────────────────────────────────────────────────────────────
# StepDownController
# ─────────────────────────────────────────────────────────────────────────────

class TestStepDownController:

    def _controller(self, start=12.0, stop=6.0) -> StepDownController:
        return StepDownController(start_bpm=start, stop_bpm=stop, increment=0.5)

    def test_initial_bpm_matches_start(self):
        ctrl = self._controller(start=12.0)
        assert ctrl.current_bpm == 12.0

    def test_prf_not_found_initially(self):
        ctrl = self._controller()
        assert ctrl.prf_found is False
        assert ctrl.confirmed_prf_bpm is None

    def test_gate_a_fails_on_bad_bpm(self):
        ctrl = self._controller(start=12.0)
        ev = ctrl.update(_bpm(8.0), _cr(0.70))
        assert ev.gate_a is False

    def test_gate_a_passes_on_matching_bpm(self):
        ctrl = self._controller(start=12.0)
        ev = ctrl.update(_bpm(12.0), _cr(0.70))
        assert ev.gate_a is True

    def test_gate_b_requires_consecutive_a(self):
        ctrl = self._controller(start=12.0)
        # 2 passes (need 3 by default)
        ctrl.update(_bpm(12.0), _cr(0.50))
        ev = ctrl.update(_bpm(12.0), _cr(0.50))
        assert ev.gate_b is False

    def test_gate_b_passes_after_n_consecutive(self):
        ctrl = self._controller(start=12.0)
        for _ in range(ctrl.gate_b_windows):
            ev = ctrl.update(_bpm(12.0), _cr(0.50))
        assert ev.gate_b is True

    def test_gate_a_reset_breaks_consecutive(self):
        ctrl = self._controller(start=12.0)
        ctrl.update(_bpm(12.0), _cr(0.50))   # A passes
        ctrl.update(_bpm(8.0),  _cr(0.50))   # A fails — reset
        ev = ctrl.update(_bpm(12.0), _cr(0.50))
        assert ev.consecutive_a == 1

    def test_gate_c_fails_low_coherence(self):
        ctrl = self._controller(start=6.0)
        ev = ctrl.update(_bpm(6.0), _cr(0.50))   # coherence < 0.65
        assert ev.gate_c is False

    def test_gate_c_passes_high_coherence(self):
        ctrl = self._controller(start=6.0)
        ev = ctrl.update(_bpm(6.0), _cr(0.70))
        assert ev.gate_c is True

    def test_prf_found_when_all_gates_pass(self):
        ctrl = self._controller(start=6.0, stop=6.0)
        # Pass gate A 3 times (gate B) with gate C each time
        for _ in range(ctrl.gate_b_windows):
            ctrl.update(_bpm(6.0), _cr(0.70))
        assert ctrl.prf_found is True
        assert ctrl.confirmed_prf_bpm == 6.0

    def test_prf_not_found_when_only_ab_pass(self):
        """Gate B without Gate C should NOT confirm PRF — just trigger step-down."""
        ctrl = self._controller(start=12.0, stop=6.0)
        for _ in range(ctrl.gate_b_windows):
            ctrl.update(_bpm(12.0), _cr(0.50))   # gate C fails (coh 0.50 < 0.65)
        assert ctrl.prf_found is False

    def test_should_step_down_when_ab_pass_c_fails(self):
        ctrl = self._controller(start=12.0, stop=6.0)
        for _ in range(ctrl.gate_b_windows):
            ctrl.update(_bpm(12.0), _cr(0.50))
        assert ctrl.should_step_down is True

    def test_should_not_step_down_after_prf_found(self):
        ctrl = self._controller(start=6.0, stop=6.0)
        for _ in range(ctrl.gate_b_windows):
            ctrl.update(_bpm(6.0), _cr(0.70))
        assert ctrl.prf_found is True
        assert ctrl.should_step_down is False

    def test_step_down_reduces_bpm(self):
        ctrl = self._controller(start=12.0, stop=6.0)
        ctrl.step_down()
        assert ctrl.current_bpm == pytest.approx(11.5, abs=0.05)

    def test_step_down_does_not_go_below_floor(self):
        ctrl = self._controller(start=6.5, stop=6.0)
        ctrl.step_down()
        assert ctrl.current_bpm == 6.0

    def test_step_down_resets_consecutive_counter(self):
        ctrl = self._controller(start=12.0, stop=6.0)
        ctrl.update(_bpm(12.0), _cr(0.50))
        ctrl.step_down()
        assert ctrl._consecutive_a == 0

    def test_at_floor_true_at_stop_bpm(self):
        ctrl = self._controller(start=6.0, stop=6.0)
        assert ctrl.at_floor is True

    def test_force_prf_sets_confirmed(self):
        ctrl = self._controller(start=12.0)
        ctrl.force_prf(7.5)
        assert ctrl.prf_found is True
        assert ctrl.confirmed_prf_bpm == 7.5
        assert ctrl.current_bpm == 7.5

    def test_invalid_breath_estimate_fails_gate_a(self):
        ctrl = self._controller(start=12.0)
        ev = ctrl.update(_bpm_invalid(), _cr(0.70))
        assert ev.gate_a is False

    def test_invalid_coherence_fails_gate_c(self):
        ctrl = self._controller(start=12.0)
        ev = ctrl.update(_bpm(12.0), _cr_invalid())
        assert ev.gate_c is False

    def test_history_grows_with_updates(self):
        ctrl = self._controller()
        ctrl.update(_bpm(12.0), _cr(0.50))
        ctrl.update(_bpm(12.0), _cr(0.50))
        assert len(ctrl.history) == 2


# ─────────────────────────────────────────────────────────────────────────────
# Session prescriber
# ─────────────────────────────────────────────────────────────────────────────

class TestSessionPrescriber:

    def test_stage_0_early_sessions_gives_entrainment(self):
        session = prescribe_session(
            stage=0, prf_status=PRF_UNKNOWN,
            total_sessions_completed=0,
        )
        assert session.practice_type == "ring_entrainment"

    def test_stage_0_after_entrainment_gives_prf_discovery(self):
        session = prescribe_session(
            stage=0, prf_status=PRF_UNKNOWN,
            total_sessions_completed=3,
        )
        assert session.practice_type == "prf_discovery"

    def test_stage_1_found_prf_gives_resonance(self):
        session = prescribe_session(
            stage=1, prf_status=PRF_FOUND,
            stored_prf_bpm=6.5,
            load_score=0.20,
        )
        assert session.practice_type == "resonance_hold"

    def test_high_stress_stage_1_gives_box(self):
        session = prescribe_session(
            stage=1, prf_status=PRF_FOUND,
            load_score=0.75,
        )
        assert session.practice_type == "box_breathing"

    def test_high_stress_stage_0_not_box(self):
        """Stage 0 should never receive box_breathing — gates don't apply yet."""
        session = prescribe_session(
            stage=0, prf_status=PRF_UNKNOWN,
            load_score=0.90,
            total_sessions_completed=5,
        )
        assert session.practice_type != "box_breathing"

    def test_stage_2_confirmed_prf_gives_plexus_hold(self):
        session = prescribe_session(
            stage=2, prf_status=PRF_CONFIRMED,
            stored_prf_bpm=6.5,
            load_score=0.20,
        )
        assert session.practice_type == "plexus_hold"

    def test_stage_2_found_only_gives_step_down(self):
        """PRF found but not confirmed at stage 2 → re-calibrate with step-down."""
        session = prescribe_session(
            stage=2, prf_status=PRF_FOUND,
            stored_prf_bpm=6.5,
        )
        assert session.practice_type in ("prf_discovery", "plexus_step_down")

    def test_stage_4_low_load_gives_silent_meditation(self):
        session = prescribe_session(
            stage=4, prf_status=PRF_CONFIRMED,
            stored_prf_bpm=6.0,
            load_score=0.10,
        )
        assert session.practice_type == "silent_meditation"

    def test_stage_4_moderate_load_gives_resonance(self):
        """Under any meaningful load, stage 4 falls back to resonance hold."""
        session = prescribe_session(
            stage=4, prf_status=PRF_CONFIRMED,
            stored_prf_bpm=6.0,
            load_score=0.45,
        )
        assert session.practice_type == "resonance_hold"

    def test_rest_session_type_gives_short_session(self):
        session = prescribe_session(
            stage=2, prf_status=PRF_CONFIRMED,
            session_type="rest",
            stored_prf_bpm=6.5,
        )
        assert session.duration_minutes <= 5

    def test_attention_anchor_propagated(self):
        session = prescribe_session(
            stage=2, prf_status=PRF_CONFIRMED,
            stored_prf_bpm=6.5,
            attention_anchor="heart",
        )
        assert session.attention_anchor == "heart"

    def test_prf_discovery_has_step_down_pacer(self):
        session = prescribe_session(
            stage=0, prf_status=PRF_UNKNOWN,
            total_sessions_completed=5,
        )
        assert session.pacer is not None
        assert session.pacer.step_down_enabled is True

    def test_resonance_no_step_down(self):
        session = prescribe_session(
            stage=1, prf_status=PRF_FOUND,
            stored_prf_bpm=6.5,
        )
        assert session.pacer is not None
        assert session.pacer.step_down_enabled is False

    def test_silent_meditation_no_pacer(self):
        session = prescribe_session(
            stage=4, prf_status=PRF_CONFIRMED,
            stored_prf_bpm=6.0,
            load_score=0.0,
        )
        assert session.pacer is None

    def test_gates_required_for_prf_discovery(self):
        session = prescribe_session(
            stage=0, prf_status=PRF_UNKNOWN,
            total_sessions_completed=5,
        )
        assert session.gates_required is True

    def test_gates_not_required_for_resonance(self):
        session = prescribe_session(
            stage=1, prf_status=PRF_FOUND,
            stored_prf_bpm=6.5,
        )
        assert session.gates_required is False

    def test_duration_override_respected(self):
        session = prescribe_session(
            stage=1, prf_status=PRF_FOUND,
            stored_prf_bpm=6.5,
            duration_minutes=7,
        )
        assert session.duration_minutes == 7

    def test_stage_unknown_prf_at_stage_1_gives_discovery(self):
        session = prescribe_session(
            stage=1, prf_status=PRF_UNKNOWN,
            total_sessions_completed=10,
        )
        assert session.practice_type == "prf_discovery"

    def test_session_notes_not_empty(self):
        session = prescribe_session(
            stage=1, prf_status=PRF_FOUND,
            stored_prf_bpm=6.5,
        )
        assert len(session.session_notes) >= 1


# ─────────────────────────────────────────────────────────────────────────────
# PracticeSession / to_dict
# ─────────────────────────────────────────────────────────────────────────────

class TestPracticeSession:

    def _make_session(self) -> PracticeSession:
        pacer = build_pacer_config("resonance_hold", target_bpm=6.5)
        return PracticeSession(
            practice_type    = "resonance_hold",
            pacer            = pacer,
            attention_anchor = None,
            duration_minutes = 10,
            gates_required   = False,
            prf_target_bpm   = 6.5,
            session_notes    = ["Breathe at 6.5 BPM."],
            tier             = 1,
        )

    def test_has_pacer_true(self):
        assert self._make_session().has_pacer() is True

    def test_has_pacer_false_for_silent(self):
        session = PracticeSession(
            practice_type="silent_meditation", pacer=None,
            attention_anchor=None, duration_minutes=20,
            gates_required=False, prf_target_bpm=6.5,
        )
        assert session.has_pacer() is False

    def test_is_step_down_false_for_resonance(self):
        assert self._make_session().is_step_down() is False

    def test_is_step_down_true_for_prf_discovery(self):
        pacer = build_pacer_config(
            "prf_discovery", target_bpm=12.0,
            step_down_enabled=True, step_down_from_bpm=12.0, step_down_to_bpm=6.0,
        )
        session = PracticeSession(
            practice_type="prf_discovery", pacer=pacer,
            attention_anchor=None, duration_minutes=15,
            gates_required=True, prf_target_bpm=None,
        )
        assert session.is_step_down() is True

    def test_to_dict_contains_required_keys(self):
        d = self._make_session().to_dict()
        for key in ("practice_type", "pacer", "attention_anchor",
                    "duration_minutes", "gates_required", "prf_target_bpm",
                    "session_notes", "tier"):
            assert key in d, f"Missing key: {key}"

    def test_to_dict_pacer_contains_timing(self):
        d = self._make_session().to_dict()
        pacer_d = d["pacer"]
        assert pacer_d is not None
        for key in ("target_bpm", "inhale_sec", "exhale_sec", "step_down_enabled"):
            assert key in pacer_d

    def test_to_dict_none_pacer_serialises_null(self):
        session = PracticeSession(
            practice_type="silent_meditation", pacer=None,
            attention_anchor=None, duration_minutes=20,
            gates_required=False, prf_target_bpm=None,
        )
        d = session.to_dict()
        assert d["pacer"] is None
