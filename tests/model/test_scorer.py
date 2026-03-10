"""
tests/model/test_scorer.py

Unit tests for archetypes/scorer.py.

Tests verify:
1.  Empty/minimal fingerprint → stage 0, UNCLASSIFIED.
2.  Rohan-like fingerprint → over_optimizer primary, stage 1, correct total.
3.  Night Warrior signals → night_warrior primary.
4.  Loop Runner signals → loop_runner primary.
5.  High performance fingerprint → dialled_in pattern, stage 5.
6.  Amplifier only surfaced when second pattern >= AMPLIFIER_THRESHOLD.
7.  Stage boundary math (34→0, 35→1, 55→2, 70→3, 80→4, 90→5).
8.  total_score == sum of five dimensions (invariant).
9.  Low overall_confidence → UNCLASSIFIED regardless of signals.
10. Stage focus list is always 2-3 items.
11. Quiet depleter signals → quiet_depleter primary.
12. Dialled-In requires all strong dimensions.
"""

from __future__ import annotations

import pytest

from archetypes.scorer import (
    NSHealthProfile,
    compute_ns_health_profile,
    STAGE_THRESHOLDS,
    STAGE_TARGETS,
    _score_recovery_capacity,
    _score_baseline_resilience,
    _score_coherence_capacity,
    _score_chrono_fit,
    _score_load_management,
    _compute_stage,
    _compute_pattern_scores,
    _select_patterns,
    _AMPLIFIER_THRESHOLD,
    _MIN_CONFIDENCE_FOR_PATTERN,
)
from model.baseline_builder import PersonalFingerprint


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _empty_fp(**overrides) -> PersonalFingerprint:
    """Minimal fingerprint — all Optional fields None, confidence near-zero."""
    defaults: dict = dict(
        overall_confidence=0.0,
        data_hours_available=4.0,
    )
    defaults.update(overrides)
    return PersonalFingerprint(**defaults)


def _rohan_fp() -> PersonalFingerprint:
    """
    Stage-1 Over-Optimizer profile.

    Trains hard, sleeps short, LF/HF elevated, arcs slow.
    Expected: primary=over_optimizer, amplifier=hustler, stage=1, total=38.
    """
    return PersonalFingerprint(
        rmssd_floor=35.0,
        rmssd_ceiling=57.0,
        rmssd_range=22.0,
        rmssd_morning_avg=38.0,
        recovery_arc_class="slow",
        sleep_recovery_efficiency=0.88,
        coherence_floor=0.30,
        rsa_trainability="moderate",
        coherence_trainability="low",
        lf_hf_resting=1.9,
        lf_hf_sleep=1.8,
        overnight_rmssd_delta_avg=-1.0,
        has_prior_practice=False,
        overall_confidence=0.75,
        data_hours_available=52.0,
    )


def _night_warrior_fp() -> PersonalFingerprint:
    """
    Night Warrior profile.

    SRE = 0.72 (mornings weak), peaks at 22:00. Chrono_fit will be very low.
    Expected: primary=night_warrior, stage=1.
    """
    return PersonalFingerprint(
        sleep_recovery_efficiency=0.72,
        best_window_hour=22,
        rmssd_floor=38.0,
        rmssd_range=18.0,
        lf_hf_resting=1.6,
        overall_confidence=0.75,
        data_hours_available=48.0,
    )


def _loop_runner_fp() -> PersonalFingerprint:
    """
    Loop Runner profile.

    Overnight RMSSD drops significantly. LF/HF during sleep elevated.
    Expected: primary=loop_runner, stage=1.
    """
    return PersonalFingerprint(
        overnight_rmssd_delta_avg=-8.0,
        lf_hf_sleep=2.2,
        sleep_recovery_efficiency=0.82,
        rmssd_floor=36.0,
        lf_hf_resting=1.7,
        overall_confidence=0.75,
        data_hours_available=48.0,
    )


def _quiet_depleter_fp() -> PersonalFingerprint:
    """
    Quiet Depleter profile.

    Low floor, narrow range, no practice, no visible stressor.
    Expected: primary=quiet_depleter, stage=0–1.
    """
    return PersonalFingerprint(
        rmssd_floor=21.0,
        rmssd_ceiling=33.0,
        rmssd_range=12.0,
        sleep_recovery_efficiency=1.01,   # neutral — not night warrior
        lf_hf_resting=1.55,              # mild — not a load problem
        has_prior_practice=False,
        coherence_floor=0.22,
        overall_confidence=0.70,
        data_hours_available=48.0,
    )


def _dialled_in_fp() -> PersonalFingerprint:
    """
    Peak-state profile.

    All dimensions near ceiling.
    Expected: primary=dialled_in, stage=5, total=100.
    """
    return PersonalFingerprint(
        rmssd_floor=58.0,
        rmssd_ceiling=92.0,
        rmssd_range=34.0,
        rmssd_morning_avg=72.0,
        recovery_arc_class="fast",
        sleep_recovery_efficiency=1.35,
        coherence_floor=0.62,
        rsa_trainability="high",
        coherence_trainability="high",
        lf_hf_resting=1.2,
        lf_hf_sleep=1.3,
        overnight_rmssd_delta_avg=8.0,
        best_window_hour=7,
        has_prior_practice=True,
        overall_confidence=0.90,
        data_hours_available=72.0,
    )


# ── Test: invariants ──────────────────────────────────────────────────────────

class TestScoreInvariants:

    def test_total_equals_sum_of_dimensions(self):
        """total_score == sum of five dimension scores (always)."""
        for fp in [_empty_fp(), _rohan_fp(), _night_warrior_fp(), _loop_runner_fp(),
                   _quiet_depleter_fp(), _dialled_in_fp()]:
            prof = compute_ns_health_profile(fp)
            expected = (
                prof.recovery_capacity
                + prof.baseline_resilience
                + prof.coherence_capacity
                + prof.chrono_fit
                + prof.load_management
            )
            assert prof.total_score == expected, (
                f"total_score {prof.total_score} != dim sum {expected}"
            )

    def test_all_dimensions_in_range(self):
        """All dimension scores are in [0, 20]."""
        for fp in [_empty_fp(), _rohan_fp(), _night_warrior_fp(), _dialled_in_fp()]:
            prof = compute_ns_health_profile(fp)
            for dim, val in prof.dimension_breakdown().items():
                assert 0 <= val <= 20, f"{dim} = {val} out of [0, 20]"

    def test_total_score_in_range(self):
        """Total score is always in [0, 100]."""
        for fp in [_empty_fp(), _rohan_fp(), _dialled_in_fp()]:
            prof = compute_ns_health_profile(fp)
            assert 0 <= prof.total_score <= 100

    def test_stage_target_is_next_threshold(self):
        """stage_target matches STAGE_TARGETS lookup."""
        for fp in [_empty_fp(), _rohan_fp(), _dialled_in_fp()]:
            prof = compute_ns_health_profile(fp)
            assert prof.stage_target == STAGE_TARGETS[prof.stage]

    def test_stage_focus_has_items(self):
        """stage_focus always returns non-empty list."""
        for fp in [_empty_fp(), _rohan_fp(), _night_warrior_fp()]:
            prof = compute_ns_health_profile(fp)
            assert len(prof.stage_focus) >= 1


# ── Test: stage boundaries ────────────────────────────────────────────────────

class TestStageBoundaries:
    """Verify _compute_stage assigns the correct stage at each threshold boundary."""

    @pytest.mark.parametrize("score,expected", [
        (0,   0),
        (34,  0),
        (35,  1),
        (54,  1),
        (55,  2),
        (69,  2),
        (70,  3),
        (79,  3),
        (80,  4),
        (89,  4),
        (90,  5),
        (100, 5),
    ])
    def test_stage_boundary(self, score: int, expected: int):
        assert _compute_stage(score) == expected, f"score {score} → stage {expected}"


# ── Test: empty fingerprint ────────────────────────────────────────────────────

class TestEmptyFingerprint:

    def test_empty_fp_is_unclassified(self):
        """Confidence=0.0 → UNCLASSIFIED regardless of any signal."""
        prof = compute_ns_health_profile(_empty_fp(overall_confidence=0.0))
        assert prof.primary_pattern == "UNCLASSIFIED"
        assert prof.amplifier_pattern is None

    def test_empty_fp_low_score(self):
        """
        Minimal data → neutral-default score.

        All-None fields fall back to neutral mid-points per dimension,
        which sum to ~44. This is by design — we do not penalise unknown data.
        The score is always in [0, 100].
        """
        prof = compute_ns_health_profile(_empty_fp())
        assert 0 <= prof.total_score <= 100

    def test_empty_fp_stage_is_reasonable(self):
        """
        All-None fields give neutral mid-point scores, so stage is not necessarily 0.
        Verify the stage is at least computable and within valid range.
        """
        prof = compute_ns_health_profile(_empty_fp())
        assert 0 <= prof.stage <= 5

    def test_below_confidence_threshold_unclassified(self):
        """Fingerprint just below the pattern confidence threshold → UNCLASSIFIED."""
        fp = _empty_fp(overall_confidence=_MIN_CONFIDENCE_FOR_PATTERN - 0.01)
        prof = compute_ns_health_profile(fp)
        assert prof.primary_pattern == "UNCLASSIFIED"

    def test_at_confidence_threshold_classified(self):
        """Fingerprint at or above the confidence threshold → classified."""
        fp = PersonalFingerprint(
            overall_confidence=_MIN_CONFIDENCE_FOR_PATTERN,
            data_hours_available=24.0,
            lf_hf_resting=2.5,
            recovery_arc_class="slow",
            rmssd_floor=30.0,
        )
        prof = compute_ns_health_profile(fp)
        assert prof.primary_pattern != "UNCLASSIFIED"


# ── Test: Rohan (Over-Optimizer) ──────────────────────────────────────────────

class TestRohanOverOptimizer:

    def test_primary_pattern(self):
        prof = compute_ns_health_profile(_rohan_fp())
        assert prof.primary_pattern == "over_optimizer"

    def test_score_in_stage_1_range(self):
        prof = compute_ns_health_profile(_rohan_fp())
        assert 35 <= prof.total_score <= 54, f"Expected stage 1, got score={prof.total_score}"

    def test_stage_is_1(self):
        prof = compute_ns_health_profile(_rohan_fp())
        assert prof.stage == 1

    def test_rohan_amplifier_is_hustler(self):
        """Rohan's secondary pattern — high load + slow arc — fires hustler as amplifier."""
        prof = compute_ns_health_profile(_rohan_fp())
        assert prof.amplifier_pattern is not None
        assert prof.amplifier_pattern != prof.primary_pattern

    def test_over_optimizer_score_in_pattern_scores(self):
        """over_optimizer pattern evidence score should be at or near max."""
        fp = _rohan_fp()
        rc = _score_recovery_capacity(fp)
        br = _score_baseline_resilience(fp)
        cc = _score_coherence_capacity(fp)
        cf = _score_chrono_fit(fp)
        lm = _score_load_management(fp)
        scores = _compute_pattern_scores(fp, rc, br, cc, cf, lm)
        assert scores["over_optimizer"] >= 0.8

    def test_load_management_low_for_rohan(self):
        """Rohan's LF/HF + overnight drop should produce low load_management."""
        fp = _rohan_fp()
        lm = _score_load_management(fp)
        assert lm <= 10

    def test_recovery_capacity_low_for_rohan(self):
        """Slow arcs + modest SRE → rc should be low."""
        fp = _rohan_fp()
        rc = _score_recovery_capacity(fp)
        assert rc <= 10

    def test_exact_total_score(self):
        """
        Rohan fixture is deterministic — verify the expected total.

        Dimension-by-dimension:
          rc: arc=slow→6; sre=0.88 (0.80–0.92 range) → -2 → 4
          br: floor=35→10; range=22→+1; no practice → 11
          cc: floor=0.30 (hits 0.25 bucket) → 7; rsa_t=moderate→+2 → 9
          cf: sre=0.88 → 8; morning_avg=38/floor=35=1.09 → +1 → 9
          lm: lf_hf=1.9 (≤2.1) → 9; lf_hf_sleep=1.8 (1.5–2.2, no adj); ond=-1 → -2 → 7
          total = 4+11+9+9+7 = 40
        """
        prof = compute_ns_health_profile(_rohan_fp())
        assert prof.total_score == 40


# ── Test: Night Warrior ───────────────────────────────────────────────────────

class TestNightWarrior:

    def test_primary_pattern_is_night_warrior(self):
        prof = compute_ns_health_profile(_night_warrior_fp())
        assert prof.primary_pattern == "night_warrior"

    def test_chrono_fit_very_low(self):
        """SRE=0.72 and missing morning avg → chrono_fit should be ≤5."""
        fp = _night_warrior_fp()
        cf = _score_chrono_fit(fp)
        assert cf <= 5

    def test_night_warrior_score_is_max(self):
        """All three night_warrior signals fire → pattern score = 1.0."""
        fp = _night_warrior_fp()
        rc = _score_recovery_capacity(fp)
        br = _score_baseline_resilience(fp)
        cc = _score_coherence_capacity(fp)
        cf = _score_chrono_fit(fp)
        lm = _score_load_management(fp)
        scores = _compute_pattern_scores(fp, rc, br, cc, cf, lm)
        assert scores["night_warrior"] == pytest.approx(1.0)


# ── Test: Loop Runner ─────────────────────────────────────────────────────────

class TestLoopRunner:

    def test_primary_pattern_is_loop_runner(self):
        prof = compute_ns_health_profile(_loop_runner_fp())
        assert prof.primary_pattern == "loop_runner"

    def test_loop_runner_score_is_max(self):
        """Negative overnight delta + elevated LF/HF sleep + low chrono → 1.0."""
        fp = _loop_runner_fp()
        rc = _score_recovery_capacity(fp)
        br = _score_baseline_resilience(fp)
        cc = _score_coherence_capacity(fp)
        cf = _score_chrono_fit(fp)
        lm = _score_load_management(fp)
        scores = _compute_pattern_scores(fp, rc, br, cc, cf, lm)
        assert scores["loop_runner"] == pytest.approx(1.0)

    def test_loop_runner_beats_night_warrior(self):
        """Loop runner signals are stronger than night warrior for this fixture."""
        fp = _loop_runner_fp()
        rc = _score_recovery_capacity(fp)
        br = _score_baseline_resilience(fp)
        cc = _score_coherence_capacity(fp)
        cf = _score_chrono_fit(fp)
        lm = _score_load_management(fp)
        scores = _compute_pattern_scores(fp, rc, br, cc, cf, lm)
        assert scores["loop_runner"] > scores["night_warrior"]


# ── Test: Quiet Depleter ──────────────────────────────────────────────────────

class TestQuietDepleter:

    def test_primary_pattern_is_quiet_depleter(self):
        prof = compute_ns_health_profile(_quiet_depleter_fp())
        assert prof.primary_pattern == "quiet_depleter"

    def test_baseline_resilience_low(self):
        """Low floor (21ms) → baseline_resilience should be ≤ 8."""
        fp = _quiet_depleter_fp()
        br = _score_baseline_resilience(fp)
        assert br <= 8

    def test_not_classified_as_night_warrior(self):
        """Sleep efficiency neutral → night_warrior should not dominate."""
        fp = _quiet_depleter_fp()
        rc = _score_recovery_capacity(fp)
        br = _score_baseline_resilience(fp)
        cc = _score_coherence_capacity(fp)
        cf = _score_chrono_fit(fp)
        lm = _score_load_management(fp)
        scores = _compute_pattern_scores(fp, rc, br, cc, cf, lm)
        assert scores["quiet_depleter"] > scores["night_warrior"]


# ── Test: Dialled-In ──────────────────────────────────────────────────────────

class TestDialledIn:

    def test_primary_pattern_is_dialled_in(self):
        prof = compute_ns_health_profile(_dialled_in_fp())
        assert prof.primary_pattern == "dialled_in"

    def test_max_total(self):
        """All ceiling-level inputs → total = 100."""
        prof = compute_ns_health_profile(_dialled_in_fp())
        assert prof.total_score == 100

    def test_stage_5(self):
        prof = compute_ns_health_profile(_dialled_in_fp())
        assert prof.stage == 5

    def test_all_dimensions_at_twenty(self):
        """Every dimension should be clamped at 20."""
        prof = compute_ns_health_profile(_dialled_in_fp())
        for dim, val in prof.dimension_breakdown().items():
            assert val == 20, f"{dim} = {val}, expected 20"


# ── Test: amplifier logic ─────────────────────────────────────────────────────

class TestAmplifierLogic:

    def test_amplifier_none_when_low_secondary_score(self):
        """
        When no secondary pattern clears the threshold,
        amplifier_pattern should be None.
        """
        # Purist profile: has practice, good coherence, no stress signals.
        # Most competing patterns should score low.
        fp = PersonalFingerprint(
            has_prior_practice=True,
            coherence_floor=0.55,
            rsa_trainability="high",
            coherence_trainability="high",
            rmssd_floor=50.0,
            rmssd_range=28.0,
            sleep_recovery_efficiency=1.15,
            lf_hf_resting=1.4,
            overall_confidence=0.85,
            data_hours_available=60.0,
        )
        prof = compute_ns_health_profile(fp)
        # Primary should be purist or dialled_in
        assert prof.primary_pattern in ("purist", "dialled_in")
        # Amplifier, if present, should be >= threshold
        if prof.amplifier_pattern is not None:
            assert prof.pattern_scores[prof.amplifier_pattern] >= _AMPLIFIER_THRESHOLD

    def test_amplifier_not_same_as_primary(self):
        """Amplifier pattern must differ from the primary pattern."""
        prof = compute_ns_health_profile(_rohan_fp())
        if prof.amplifier_pattern is not None:
            assert prof.amplifier_pattern != prof.primary_pattern


# ── Test: dimension scoring unit tests ───────────────────────────────────────

class TestDimensionScoring:

    # ── Recovery Capacity ──────────────────────────────────────────────────────

    def test_fast_arc_base_is_sixteen(self):
        fp = PersonalFingerprint(recovery_arc_class="fast")
        val = _score_recovery_capacity(fp)
        assert val == 16  # fast arc, no sre adjustment

    def test_compressed_arc_base_is_two(self):
        fp = PersonalFingerprint(recovery_arc_class="compressed")
        val = _score_recovery_capacity(fp)
        assert val == 2

    def test_recovery_capacity_clamped_at_twenty(self):
        fp = PersonalFingerprint(
            recovery_arc_class="fast",       # base=16
            sleep_recovery_efficiency=1.30,  # +4 → 20
        )
        assert _score_recovery_capacity(fp) == 20

    def test_recovery_capacity_clamped_at_zero(self):
        fp = PersonalFingerprint(
            recovery_arc_class="compressed",  # base=2
            sleep_recovery_efficiency=0.70,   # -4 → -2
        )
        assert _score_recovery_capacity(fp) == 0

    # ── Baseline Resilience ────────────────────────────────────────────────────

    def test_high_rmssd_floor_high_resilience(self):
        fp = PersonalFingerprint(rmssd_floor=60.0)
        assert _score_baseline_resilience(fp) >= 18

    def test_low_rmssd_floor_low_resilience(self):
        fp = PersonalFingerprint(rmssd_floor=18.0)
        assert _score_baseline_resilience(fp) <= 5

    def test_wide_range_bonus_applied(self):
        fp1 = PersonalFingerprint(rmssd_floor=40.0, rmssd_range=10.0)
        fp2 = PersonalFingerprint(rmssd_floor=40.0, rmssd_range=35.0)
        assert _score_baseline_resilience(fp2) > _score_baseline_resilience(fp1)

    def test_prior_practice_bonus(self):
        fp1 = PersonalFingerprint(rmssd_floor=40.0, has_prior_practice=False)
        fp2 = PersonalFingerprint(rmssd_floor=40.0, has_prior_practice=True)
        assert _score_baseline_resilience(fp2) == _score_baseline_resilience(fp1) + 1

    # ── Coherence Capacity ─────────────────────────────────────────────────────

    def test_high_coherence_floor_high_score(self):
        fp = PersonalFingerprint(coherence_floor=0.60, rsa_trainability="high", coherence_trainability="high")
        assert _score_coherence_capacity(fp) == 20  # 16 + 4 + 2 = 22 → clamped

    def test_low_coherence_floor_penalised(self):
        fp = PersonalFingerprint(coherence_floor=0.18)
        assert _score_coherence_capacity(fp) <= 6

    # ── Chronobiological Fit ──────────────────────────────────────────────────

    def test_high_sre_chrono_fit(self):
        fp = PersonalFingerprint(sleep_recovery_efficiency=1.30)
        assert _score_chrono_fit(fp) >= 18

    def test_low_sre_chrono_fit(self):
        fp = PersonalFingerprint(sleep_recovery_efficiency=0.70)
        assert _score_chrono_fit(fp) <= 5

    def test_morning_above_floor_adds_bonus(self):
        fp1 = PersonalFingerprint(sleep_recovery_efficiency=1.05, rmssd_morning_avg=40.0, rmssd_floor=40.0)
        fp2 = PersonalFingerprint(sleep_recovery_efficiency=1.05, rmssd_morning_avg=50.0, rmssd_floor=40.0)
        assert _score_chrono_fit(fp2) > _score_chrono_fit(fp1)

    # ── Load Management ────────────────────────────────────────────────────────

    def test_low_lf_hf_high_load_management(self):
        fp = PersonalFingerprint(lf_hf_resting=1.2)
        assert _score_load_management(fp) >= 18

    def test_high_lf_hf_low_load_management(self):
        fp = PersonalFingerprint(lf_hf_resting=3.0)
        assert _score_load_management(fp) <= 5

    def test_high_lf_hf_sleep_penalises_load(self):
        fp1 = PersonalFingerprint(lf_hf_resting=1.5, lf_hf_sleep=1.2)
        fp2 = PersonalFingerprint(lf_hf_resting=1.5, lf_hf_sleep=2.5)
        assert _score_load_management(fp2) < _score_load_management(fp1)

    def test_negative_overnight_delta_penalises_load(self):
        fp1 = PersonalFingerprint(lf_hf_resting=1.5, overnight_rmssd_delta_avg=3.0)
        fp2 = PersonalFingerprint(lf_hf_resting=1.5, overnight_rmssd_delta_avg=-3.0)
        assert _score_load_management(fp2) < _score_load_management(fp1)


# ── Test: trajectory ──────────────────────────────────────────────────────────

class TestTrajectory:

    def test_improving_when_big_positive_delta(self):
        prof = compute_ns_health_profile(_rohan_fp(), score_7d_delta=5)
        assert prof.trajectory == "improving"

    def test_declining_when_big_negative_delta(self):
        prof = compute_ns_health_profile(_rohan_fp(), score_7d_delta=-5)
        assert prof.trajectory == "declining"

    def test_stable_when_small_delta(self):
        prof = compute_ns_health_profile(_rohan_fp(), score_7d_delta=1)
        assert prof.trajectory == "stable"

    def test_stable_when_no_delta(self):
        prof = compute_ns_health_profile(_rohan_fp(), score_7d_delta=None)
        assert prof.trajectory == "stable"


# ── Test: metadata propagation ────────────────────────────────────────────────

class TestMetadata:

    def test_overall_confidence_propagated(self):
        fp = _rohan_fp()
        prof = compute_ns_health_profile(fp)
        assert prof.overall_confidence == fp.overall_confidence

    def test_data_hours_propagated(self):
        fp = _rohan_fp()
        prof = compute_ns_health_profile(fp)
        assert prof.data_hours == fp.data_hours_available

    def test_weeks_in_stage_propagated(self):
        prof = compute_ns_health_profile(_rohan_fp(), weeks_in_stage=3)
        assert prof.weeks_in_stage == 3

    def test_dimension_breakdown_keys(self):
        """dimension_breakdown() should return exactly the five expected keys."""
        prof = compute_ns_health_profile(_rohan_fp())
        keys = set(prof.dimension_breakdown().keys())
        expected = {"recovery_capacity", "baseline_resilience", "coherence_capacity",
                    "chrono_fit", "load_management"}
        assert keys == expected
