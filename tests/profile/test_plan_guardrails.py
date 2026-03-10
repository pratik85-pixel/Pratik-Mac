"""
tests/profile/test_plan_guardrails.py

Unit tests for profile/plan_guardrails.py (Layer 3 — deterministic rules).

All tests are pure-Python — no DB, no async.
"""

from __future__ import annotations

import pytest

from profile.plan_guardrails import validate_plan, ValidatedPlan
from profile.profile_schema import (
    PlanItem,
    UnifiedProfile,
    PhysiologicalTraits,
    PsychologicalTraits,
    BehaviouralPreferences,
    EngagementProfile,
    CoachRelationship,
)


# ── Test helpers ──────────────────────────────────────────────────────────────

def _make_item(
    slug: str,
    priority: str = "recommended",
    duration_min: int = 20,
    reason: str = "test",
) -> PlanItem:
    return PlanItem(slug=slug, priority=priority, duration_min=duration_min, reason=reason)


def _make_profile(
    *,
    discipline_index: float = 60.0,
    social_energy_type: str = "ambivert",
    engagement_tier: str = "medium",
) -> UnifiedProfile:
    return UnifiedProfile(
        user_id="test-user",
        physio=PhysiologicalTraits(),
        psych=PsychologicalTraits(
            discipline_index=discipline_index,
            social_energy_type=social_energy_type,
        ),
        behaviour=BehaviouralPreferences(),
        engagement=EngagementProfile(engagement_tier=engagement_tier),
        coach_rel=CoachRelationship(),
    )


# ── R1: Invalid slug removal ──────────────────────────────────────────────────

class TestR1InvalidSlugs:
    def test_valid_slug_passes(self):
        items = [_make_item("coherence_breathing")]
        profile = _make_profile()
        result = validate_plan(items, profile)
        slugs = [i.slug for i in result.items]
        assert "coherence_breathing" in slugs

    def test_invalid_slug_removed(self):
        items = [_make_item("fake_activity_xyz"), _make_item("meditation")]
        profile = _make_profile()
        result = validate_plan(items, profile)
        slugs = [i.slug for i in result.items]
        assert "fake_activity_xyz" not in slugs
        assert "meditation" in slugs

    def test_all_invalid_triggers_fallback(self):
        """R1 removes all + R8 injects fallback breathing."""
        items = [_make_item("not_a_slug"), _make_item("also_fake")]
        profile = _make_profile()
        result = validate_plan(items, profile)
        assert len(result.items) >= 1
        assert result.was_modified
        assert any("R1" in n for n in result.guardrail_notes)
        assert any("R8" in n for n in result.guardrail_notes)


# ── R2: Duration bounds ────────────────────────────────────────────────────────

class TestR2DurationBounds:
    def test_duration_below_floor_clamped(self):
        # meditation has explicit bounds (5, 45) in _DURATION_BOUNDS
        items = [_make_item("meditation", duration_min=1)]
        profile = _make_profile()
        result = validate_plan(items, profile)
        item = next(i for i in result.items if i.slug == "meditation")
        assert item.duration_min >= 5
        assert result.was_modified

    def test_duration_above_ceiling_clamped(self):
        items = [_make_item("meditation", duration_min=999)]
        profile = _make_profile()
        result = validate_plan(items, profile)
        item = next(i for i in result.items if i.slug == "meditation")
        assert item.duration_min <= 45

    def test_duration_in_range_unchanged(self):
        items = [_make_item("meditation", duration_min=20)]
        profile = _make_profile()
        result = validate_plan(items, profile)
        item = next(i for i in result.items if i.slug == "meditation")
        assert item.duration_min == 20


# ── R3: Must-do cap ───────────────────────────────────────────────────────────

class TestR3MustDoCap:
    def test_high_discipline_allows_2_must_do(self):
        items = [
            _make_item("coherence_breathing", priority="must_do"),
            _make_item("walking", priority="must_do"),
        ]
        profile = _make_profile(discipline_index=70.0)
        result = validate_plan(items, profile)
        must_dos = [i for i in result.items if i.priority == "must_do"]
        assert len(must_dos) == 2
        assert not any("R3" in n for n in result.guardrail_notes)

    def test_low_discipline_caps_at_1_must_do(self):
        items = [
            _make_item("coherence_breathing", priority="must_do"),
            _make_item("walking", priority="must_do"),
        ]
        profile = _make_profile(discipline_index=30.0)
        result = validate_plan(items, profile)
        must_dos = [i for i in result.items if i.priority == "must_do"]
        assert len(must_dos) == 1
        assert result.was_modified

    def test_excess_must_do_demoted_to_recommended(self):
        items = [
            _make_item("coherence_breathing", priority="must_do"),
            _make_item("walking", priority="must_do"),
            _make_item("music", priority="must_do"),
        ]
        profile = _make_profile(discipline_index=70.0)
        result = validate_plan(items, profile)
        must_dos = [i for i in result.items if i.priority == "must_do"]
        assert len(must_dos) <= 2
        # Excess demoted to recommended, all slugs still present
        all_slugs = [i.slug for i in result.items]
        assert "music" in all_slugs


# ── R4: Red day ───────────────────────────────────────────────────────────────

class TestR4RedDay:
    def test_work_sprint_removed_on_red_day(self):
        items = [_make_item("work_sprint"), _make_item("meditation")]
        profile = _make_profile()
        result = validate_plan(items, profile, readiness_score=30)
        slugs = [i.slug for i in result.items]
        assert "work_sprint" not in slugs
        assert any("R4" in n for n in result.guardrail_notes)

    def test_sports_removed_on_red_day(self):
        items = [_make_item("sports"), _make_item("meditation")]
        profile = _make_profile()
        result = validate_plan(items, profile, readiness_score=35)
        slugs = [i.slug for i in result.items]
        assert "sports" not in slugs

    def test_cold_shower_removed_on_red_day(self):
        items = [_make_item("cold_shower"), _make_item("meditation")]
        profile = _make_profile()
        result = validate_plan(items, profile, readiness_score=20)
        slugs = [i.slug for i in result.items]
        assert "cold_shower" not in slugs

    def test_green_day_keeps_work_sprint(self):
        items = [_make_item("work_sprint"), _make_item("meditation")]
        profile = _make_profile()
        result = validate_plan(items, profile, readiness_score=80)
        slugs = [i.slug for i in result.items]
        assert "work_sprint" in slugs


# ── R5: Introvert + high stress ───────────────────────────────────────────────

class TestR5IntrovertStress:
    def test_social_time_removed_for_introvert_high_stress(self):
        items = [_make_item("social_time"), _make_item("meditation")]
        profile = _make_profile(social_energy_type="introvert")
        result = validate_plan(items, profile, stress_score=80)
        slugs = [i.slug for i in result.items]
        assert "social_time" not in slugs
        assert any("R5" in n for n in result.guardrail_notes)

    def test_social_time_kept_for_extrovert_high_stress(self):
        items = [_make_item("social_time"), _make_item("meditation")]
        profile = _make_profile(social_energy_type="extrovert")
        result = validate_plan(items, profile, stress_score=80)
        slugs = [i.slug for i in result.items]
        assert "social_time" in slugs

    def test_social_time_kept_for_introvert_low_stress(self):
        items = [_make_item("social_time"), _make_item("meditation")]
        profile = _make_profile(social_energy_type="introvert")
        result = validate_plan(items, profile, stress_score=40)
        slugs = [i.slug for i in result.items]
        assert "social_time" in slugs


# ── R6: Total items cap ───────────────────────────────────────────────────────

class TestR6TotalCap:
    def test_over_6_items_truncated(self):
        # 7 valid CATALOG slugs — R6 must truncate to 6
        items = [
            _make_item("coherence_breathing"),
            _make_item("walking"),
            _make_item("nap"),
            _make_item("meditation"),
            _make_item("music"),
            _make_item("book_reading"),
            _make_item("nature_time"),
        ]
        profile = _make_profile()
        result = validate_plan(items, profile)
        assert len(result.items) <= 6
        assert any("R6" in n for n in result.guardrail_notes)

    def test_must_do_preserved_over_optional_when_truncating(self):
        # 7 valid slugs: 1 must_do + 6 optional — must_do survives truncation
        items = [
            _make_item("nature_time", priority="optional"),
            _make_item("entertainment", priority="optional"),
            _make_item("music", priority="optional"),
            _make_item("book_reading", priority="optional"),
            _make_item("meditation", priority="optional"),
            _make_item("walking", priority="optional"),
            _make_item("coherence_breathing", priority="must_do"),
        ]
        profile = _make_profile()
        result = validate_plan(items, profile)
        slugs = [i.slug for i in result.items]
        assert "coherence_breathing" in slugs
        assert len(result.items) <= 6


# ── R7: At-risk / churned engagement injection ────────────────────────────────

class TestR7EngagementInjection:
    def test_at_risk_user_gets_breathing_if_no_frictionless(self):
        items = [_make_item("sports")]
        profile = _make_profile(engagement_tier="at_risk")
        result = validate_plan(items, profile)
        slugs = [i.slug for i in result.items]
        assert "breathing" in slugs
        assert any("R7" in n for n in result.guardrail_notes)

    def test_churned_user_gets_breathing_if_no_frictionless(self):
        items = [_make_item("work_sprint")]
        profile = _make_profile(engagement_tier="churned")
        result = validate_plan(items, profile, readiness_score=80)
        slugs = [i.slug for i in result.items]
        assert "breathing" in slugs

    def test_at_risk_user_with_existing_frictionless_no_injection(self):
        # book_reading is in the frictionless set — R7 should not inject
        items = [_make_item("book_reading"), _make_item("sports")]
        profile = _make_profile(engagement_tier="at_risk")
        result = validate_plan(items, profile)
        notes = " ".join(result.guardrail_notes)
        assert "R7" not in notes

    def test_medium_user_not_injected(self):
        items = [_make_item("sports")]
        profile = _make_profile(engagement_tier="medium")
        result = validate_plan(items, profile)
        notes = " ".join(result.guardrail_notes)
        assert "R7" not in notes


# ── R8: Non-empty fallback ────────────────────────────────────────────────────

class TestR8NonEmptyFallback:
    def test_all_removed_injects_fallback(self):
        # All invalid slugs → R1 removes all → R8 injects fallback
        items = [_make_item("zzz_fake_slug")]
        profile = _make_profile()
        result = validate_plan(items, profile)
        assert len(result.items) >= 1
        assert any("R8" in n for n in result.guardrail_notes)
        assert result.items[0].slug == "breathing"

    def test_non_empty_plan_no_r8(self):
        # A valid CATALOG slug produces a non-empty plan — R8 must not fire
        items = [_make_item("meditation")]
        profile = _make_profile()
        result = validate_plan(items, profile)
        assert not any("R8" in n for n in result.guardrail_notes)


# ── Combined scenarios ─────────────────────────────────────────────────────────

class TestCombinedScenarios:
    def test_red_day_introvert_high_stress_plan(self):
        """Red day + introvert + high stress → no social_time, no work_sprint; restorative items survive."""
        items = [
            _make_item("social_time"),
            _make_item("work_sprint"),
            _make_item("meditation"),
            _make_item("music"),
        ]
        profile = _make_profile(social_energy_type="introvert")
        result = validate_plan(items, profile, readiness_score=30, stress_score=85)
        slugs = [i.slug for i in result.items]
        assert "social_time" not in slugs
        assert "work_sprint" not in slugs
        assert "meditation" in slugs
        assert "music" in slugs

    def test_churned_user_red_day_gets_minimal_safe_plan(self):
        items = [
            _make_item("sports"),
            _make_item("cold_shower"),
        ]
        profile = _make_profile(engagement_tier="churned")
        result = validate_plan(items, profile, readiness_score=20)
        slugs = [i.slug for i in result.items]
        assert "sports" not in slugs
        assert "cold_shower" not in slugs
        assert "breathing" in slugs
        assert len(result.items) >= 1

    def test_was_modified_false_for_clean_plan(self):
        # coherence_breathing is in CATALOG; 10 min is within default bounds (5, 120)
        items = [_make_item("coherence_breathing", priority="must_do", duration_min=10)]
        profile = _make_profile()
        result = validate_plan(items, profile, readiness_score=75)
        assert not result.was_modified
