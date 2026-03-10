"""
tests/profile/test_nightly_analyst.py

Unit tests for profile/nightly_analyst.py (Layer 1 + Layer 2 fallbacks).

All tests run in offline mode (llm_client=None) — no actual LLM calls.
"""

from __future__ import annotations

from datetime import date

import pytest

from profile.nightly_analyst import (
    run_layer1_narrative,
    run_layer2_plan,
    _fallback_narrative,
    _fallback_plan,
    _parse_plan_json,
)
from profile.profile_schema import (
    UnifiedProfile,
    PhysiologicalTraits,
    PsychologicalTraits,
    BehaviouralPreferences,
    EngagementProfile,
    CoachRelationship,
    PlanItem,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

_TODAY = date(2025, 6, 1)


def _make_profile(
    *,
    social_energy_type: str = "ambivert",
    discipline_index: float = 55.0,
    streak_current: int = 5,
    engagement_tier: str = "medium",
    sessions_last7: int = 3,
    prf_bpm: float = 60.0,
    mood_baseline: str = "moderate",
    narrative_version: int = 1,
) -> UnifiedProfile:
    return UnifiedProfile(
        user_id="test-user-id",
        archetype_primary="harmony_seeker",
        archetype_secondary="achiever",
        training_level=2,
        narrative_version=narrative_version,
        physio=PhysiologicalTraits(
            prf_bpm=prf_bpm,
            prf_status="PRF_CONFIRMED",
            coherence_trainability="moderate",
            recovery_arc_speed="normal",
        ),
        psych=PsychologicalTraits(
            social_energy_type=social_energy_type,
            anxiety_sensitivity=0.6,
            discipline_index=discipline_index,
            streak_current=streak_current,
            mood_baseline=mood_baseline,
        ),
        behaviour=BehaviouralPreferences(
            movement_enjoyed=["walking", "cycling"],
            decompress_via=["music"],
        ),
        engagement=EngagementProfile(
            sessions_last7=sessions_last7,
            engagement_tier=engagement_tier,
            morning_read_streak=streak_current,
        ),
        coach_rel=CoachRelationship(
            preferred_tone="compassion",
            best_nudge_window="08:00",
        ),
    )


# ── run_layer1_narrative (fallback mode, no LLM) ─────────────────────────────

class TestLayer1Narrative:
    def test_populates_coach_narrative(self):
        profile = _make_profile()
        result = run_layer1_narrative(profile, llm_client=None, today=_TODAY)
        assert result.coach_narrative is not None
        assert len(result.coach_narrative) > 0

    def test_narrative_contains_required_sections(self):
        profile = _make_profile()
        run_layer1_narrative(profile, llm_client=None, today=_TODAY)
        narrative = profile.coach_narrative
        assert "PERSONALITY SNAPSHOT" in narrative
        assert "PHYSIOLOGICAL TRAITS" in narrative
        assert "PSYCHOLOGICAL TRAITS" in narrative
        assert "BEHAVIOURAL PATTERNS" in narrative
        assert "ENGAGEMENT PROFILE" in narrative
        assert "COACH RELATIONSHIP" in narrative
        assert "WATCH TODAY" in narrative

    def test_narrative_includes_date(self):
        profile = _make_profile()
        run_layer1_narrative(profile, llm_client=None, today=_TODAY)
        assert "2025-06-01" in profile.coach_narrative

    def test_narrative_includes_engagement_tier(self):
        profile = _make_profile(engagement_tier="at_risk")
        run_layer1_narrative(profile, llm_client=None, today=_TODAY)
        assert "at_risk" in profile.coach_narrative

    def test_narrative_includes_discipline_index(self):
        profile = _make_profile(discipline_index=42.0)
        run_layer1_narrative(profile, llm_client=None, today=_TODAY)
        assert "42" in profile.coach_narrative

    def test_returns_same_profile_object(self):
        profile = _make_profile()
        result = run_layer1_narrative(profile, llm_client=None, today=_TODAY)
        assert result is profile

    def test_previous_narrative_not_overwritten(self):
        profile = _make_profile(narrative_version=2)
        profile.previous_narrative = "Old narrative from v1"
        run_layer1_narrative(profile, llm_client=None, today=_TODAY)
        # coach_narrative is updated; previous_narrative stays as is
        assert profile.previous_narrative == "Old narrative from v1"

    def test_llm_fallback_on_exception(self):
        """Should not raise — must fall back gracefully."""
        class FailingLLM:
            def chat(self, system: str, user: str) -> str:
                raise RuntimeError("API error")

        profile = _make_profile()
        result = run_layer1_narrative(profile, llm_client=FailingLLM(), today=_TODAY)
        assert result.coach_narrative is not None


# ── run_layer2_plan (fallback mode, no LLM) ───────────────────────────────────

class TestLayer2Plan:
    def test_plan_populated(self):
        profile = _make_profile()
        profile = run_layer1_narrative(profile, llm_client=None, today=_TODAY)
        result = run_layer2_plan(profile, llm_client=None, readiness_score=65, today=_TODAY)
        assert len(result.suggested_plan) > 0

    def test_plan_for_date_set(self):
        profile = _make_profile()
        run_layer2_plan(profile, llm_client=None, today=_TODAY)
        assert profile.plan_for_date == _TODAY

    def test_green_day_includes_breathing(self):
        profile = _make_profile()
        run_layer2_plan(profile, llm_client=None, readiness_score=75, today=_TODAY)
        slugs = [i.slug for i in profile.suggested_plan]
        assert "breathing" in slugs

    def test_green_day_includes_walking(self):
        profile = _make_profile()
        run_layer2_plan(profile, llm_client=None, readiness_score=80, today=_TODAY)
        slugs = [i.slug for i in profile.suggested_plan]
        assert "walking" in slugs

    def test_red_day_minimal_plan(self):
        profile = _make_profile()
        run_layer2_plan(profile, llm_client=None, readiness_score=25, today=_TODAY)
        assert len(profile.suggested_plan) == 1
        assert profile.suggested_plan[0].slug == "breathing"
        assert profile.suggested_plan[0].duration_min == 5

    def test_yellow_day_has_optional(self):
        profile = _make_profile()
        run_layer2_plan(profile, llm_client=None, readiness_score=55, today=_TODAY)
        priorities = [i.priority for i in profile.suggested_plan]
        assert "optional" in priorities

    def test_all_plan_items_have_required_fields(self):
        profile = _make_profile()
        run_layer2_plan(profile, llm_client=None, readiness_score=65, today=_TODAY)
        for item in profile.suggested_plan:
            assert item.slug
            assert item.priority in ("must_do", "recommended", "optional")
            assert isinstance(item.duration_min, int)
            assert item.reason

    def test_returns_same_profile_object(self):
        profile = _make_profile()
        result = run_layer2_plan(profile, llm_client=None, readiness_score=65)
        assert result is profile

    def test_llm_fallback_on_exception(self):
        class FailingLLM:
            def chat(self, system: str, user: str) -> str:
                raise RuntimeError("API error")

        profile = _make_profile()
        run_layer1_narrative(profile, llm_client=None, today=_TODAY)
        result = run_layer2_plan(
            profile, llm_client=FailingLLM(), readiness_score=65, today=_TODAY
        )
        assert len(result.suggested_plan) > 0

    def test_llm_empty_response_uses_fallback(self):
        class EmptyLLM:
            def chat(self, system: str, user: str) -> str:
                return ""

        profile = _make_profile()
        run_layer1_narrative(profile, llm_client=None, today=_TODAY)
        result = run_layer2_plan(
            profile, llm_client=EmptyLLM(), readiness_score=65, today=_TODAY
        )
        assert len(result.suggested_plan) > 0


# ── _fallback_narrative directly ─────────────────────────────────────────────

class TestFallbackNarrative:
    def test_no_prf_shows_not_found(self):
        profile = _make_profile(prf_bpm=None)
        profile.physio.prf_bpm = None
        narrative = _fallback_narrative(profile, _TODAY)
        assert "Not yet found" in narrative

    def test_version_shown_in_header(self):
        profile = _make_profile(narrative_version=5)
        narrative = _fallback_narrative(profile, _TODAY)
        assert "v5" in narrative

    def test_data_confidence_percentage_shown(self):
        profile = _make_profile()
        profile.data_confidence = 0.72
        narrative = _fallback_narrative(profile, _TODAY)
        assert "72%" in narrative


# ── _fallback_plan directly ───────────────────────────────────────────────────

class TestFallbackPlan:
    def test_green_day_2_items(self):
        profile = _make_profile()
        plan = _fallback_plan(profile, readiness_score=80)
        assert len(plan) == 2

    def test_yellow_day_2_items(self):
        profile = _make_profile()
        plan = _fallback_plan(profile, readiness_score=55)
        assert len(plan) == 2

    def test_red_day_1_item(self):
        profile = _make_profile()
        plan = _fallback_plan(profile, readiness_score=30)
        assert len(plan) == 1

    def test_none_readiness_uses_yellow(self):
        profile = _make_profile()
        plan = _fallback_plan(profile, readiness_score=None)
        assert len(plan) >= 1

    def test_all_plans_include_breathing(self):
        profile = _make_profile()
        for score in [80, 55, 30]:
            plan = _fallback_plan(profile, readiness_score=score)
            slugs = [i.slug for i in plan]
            assert "breathing" in slugs


# ── _parse_plan_json ──────────────────────────────────────────────────────────

class TestParsePlanJson:
    def test_valid_json_array(self):
        raw = '[{"slug": "breathing", "priority": "must_do", "duration_min": 10, "reason": "test"}]'
        items = _parse_plan_json(raw)
        assert len(items) == 1
        assert items[0].slug == "breathing"
        assert items[0].priority == "must_do"
        assert items[0].duration_min == 10

    def test_json_with_markdown_fences(self):
        raw = '```json\n[{"slug":"breathing","priority":"must_do","duration_min":10,"reason":"r"}]\n```'
        items = _parse_plan_json(raw)
        assert len(items) == 1
        assert items[0].slug == "breathing"

    def test_invalid_priority_defaults_to_recommended(self):
        raw = '[{"slug": "walking", "priority": "unknown", "duration_min": 20, "reason": "test"}]'
        items = _parse_plan_json(raw)
        assert items[0].priority == "recommended"

    def test_string_duration_coerced_to_int(self):
        raw = '[{"slug": "meditation", "priority": "optional", "duration_min": "15", "reason": "r"}]'
        items = _parse_plan_json(raw)
        assert items[0].duration_min == 15

    def test_missing_slug_skipped(self):
        raw = '[{"priority": "must_do", "duration_min": 10, "reason": "r"}]'
        items = _parse_plan_json(raw)
        assert items == []

    def test_completely_invalid_json_returns_empty(self):
        items = _parse_plan_json("not json at all")
        assert items == []

    def test_empty_string_returns_empty(self):
        items = _parse_plan_json("")
        assert items == []

    def test_multiple_items_parsed(self):
        raw = '''[
            {"slug":"breathing","priority":"must_do","duration_min":10,"reason":"r1"},
            {"slug":"walking","priority":"recommended","duration_min":20,"reason":"r2"}
        ]'''
        items = _parse_plan_json(raw)
        assert len(items) == 2
        assert items[0].slug == "breathing"
        assert items[1].slug == "walking"

    def test_reason_truncated_at_300_chars(self):
        long_reason = "x" * 400
        raw = f'[{{"slug":"breathing","priority":"must_do","duration_min":10,"reason":"{long_reason}"}}]'
        items = _parse_plan_json(raw)
        assert len(items[0].reason) <= 300
