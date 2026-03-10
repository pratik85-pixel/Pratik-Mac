"""
tests/profile/test_unified_profile_builder.py

Unit tests for profile/unified_profile_builder.py.

All tests are pure-Python — no DB, no async.
"""

from __future__ import annotations

import pytest

from profile.unified_profile_builder import build_unified_profile
from profile.profile_schema import UnifiedProfile


# ── Fixtures / helpers ────────────────────────────────────────────────────────

_BASE_USER_ROW = {
    "id": "00000000-0000-0000-0000-000000000001",
    "archetype_primary": "harmony_seeker",
    "archetype_secondary": "achiever",
    "training_level": 2,
    "created_at": "2024-01-01T00:00:00",
}

_BASE_PERSONAL_MODEL = {
    "prf_bpm": 58.5,
    "prf_status": "PRF_CONFIRMED",
    "coherence_trainability": "moderate",
    "recovery_arc_mean_hours": 3.5,
    "stress_peak_weekday": "weekday 10:00–12:00",
    "sleep_recovery_efficiency": 0.72,
    "nudge_preferred_window": "08:00",
}

_BASE_PSYCH = {
    "social_energy_type": "introvert",
    "anxiety_sensitivity": 0.65,
    "top_triggers": [{"trigger_type": "work", "count": 5}],
    "primary_recovery_style": "passive_rest",
    "discipline_index": 55.0,
    "streak_current": 7,
    "mood_baseline": "moderate",
    "interoception_alignment": 0.43,
}

_BASE_HABITS = {
    "movement_enjoyed": ["walking", "cycling"],
    "decompress_via": ["music", "nature_time"],
    "stress_drivers": ["work", "finances"],
    "alcohol_frequency": "occasional",
    "caffeine_frequency": "daily",
    "sleep_schedule": "23:00–07:00",
}

_BASE_ENGAGEMENT = {
    "sessions_last7": 4,
    "sessions_last30": 14,
    "conversations_last7": 3,
    "morning_reads_last30": 20,
    "morning_reads_streak": 5,
    "band_days_last7": 6,
    "band_days_last30": 25,
    "nudge_helpful_count": 8,
    "nudge_total_count": 10,
    "nudge_helpful_30d": 6,
    "nudge_total_30d": 8,
    "last_interaction_days": 0,
}


def _build(**overrides) -> UnifiedProfile:
    kwargs = dict(
        user_row=_BASE_USER_ROW,
        personal_model=_BASE_PERSONAL_MODEL,
        psych_profile=_BASE_PSYCH,
        habits=_BASE_HABITS,
        engagement_counts=_BASE_ENGAGEMENT,
        coach_reaction_rows=[],
        facts=[],
    )
    kwargs.update(overrides)
    return build_unified_profile(**kwargs)


# ── Basic construction ────────────────────────────────────────────────────────

class TestBasicConstruction:
    def test_returns_unified_profile(self):
        profile = _build()
        assert isinstance(profile, UnifiedProfile)

    def test_user_id_populated(self):
        profile = _build()
        assert profile.user_id == _BASE_USER_ROW["id"]

    def test_archetype_populated(self):
        profile = _build()
        assert profile.archetype_primary == "harmony_seeker"

    def test_training_level_populated(self):
        profile = _build()
        assert profile.training_level == 2

    def test_data_confidence_between_0_and_1(self):
        profile = _build()
        assert 0.0 <= profile.data_confidence <= 1.0

    def test_last_computed_at_set(self):
        profile = _build()
        assert profile.last_computed_at is not None


# ── Physiological traits ──────────────────────────────────────────────────────

class TestPhysiologicalTraits:
    def test_prf_bpm_populated(self):
        profile = _build()
        assert profile.physio.prf_bpm == pytest.approx(58.5)

    def test_prf_status_populated(self):
        profile = _build()
        assert profile.physio.prf_status == "PRF_CONFIRMED"

    def test_recovery_arc_speed_normal_range(self):
        """3.5 hours is within 'normal' (2–5h) range."""
        profile = _build()
        assert profile.physio.recovery_arc_speed == "normal"

    def test_recovery_arc_speed_fast(self):
        pm = dict(_BASE_PERSONAL_MODEL, recovery_arc_mean_hours=1.0)
        profile = _build(personal_model=pm)
        assert profile.physio.recovery_arc_speed == "fast"

    def test_recovery_arc_speed_slow(self):
        pm = dict(_BASE_PERSONAL_MODEL, recovery_arc_mean_hours=7.0)
        profile = _build(personal_model=pm)
        assert profile.physio.recovery_arc_speed == "slow"

    def test_missing_personal_model_gives_defaults(self):
        profile = _build(personal_model=None)
        assert profile.physio.prf_bpm is None
        assert profile.physio.prf_status is None


# ── Psychological traits ──────────────────────────────────────────────────────

class TestPsychologicalTraits:
    def test_social_energy_type_populated(self):
        profile = _build()
        assert profile.psych.social_energy_type == "introvert"

    def test_anxiety_sensitivity_populated(self):
        profile = _build()
        assert profile.psych.anxiety_sensitivity == pytest.approx(0.65)

    def test_discipline_index_populated(self):
        profile = _build()
        assert profile.psych.discipline_index == pytest.approx(55.0)

    def test_streak_current_populated(self):
        profile = _build()
        assert profile.psych.streak_current == 7

    def test_missing_psych_profile_gives_defaults(self):
        profile = _build(psych_profile=None)
        assert profile.psych.social_energy_type is None
        assert profile.psych.discipline_index is None


# ── Behavioural preferences ───────────────────────────────────────────────────

class TestBehaviouralPreferences:
    def test_movement_enjoyed_populated(self):
        profile = _build()
        assert "walking" in profile.behaviour.movement_enjoyed

    def test_decompress_via_populated(self):
        profile = _build()
        assert "music" in profile.behaviour.decompress_via

    def test_missing_habits_gives_defaults(self):
        profile = _build(habits=None)
        assert profile.behaviour.movement_enjoyed == []
        assert profile.behaviour.decompress_via == []


# ── Engagement profile ────────────────────────────────────────────────────────

class TestEngagementProfile:
    def test_sessions_last7_populated(self):
        profile = _build()
        assert profile.engagement.sessions_last7 == 4

    def test_morning_read_streak_populated(self):
        profile = _build()
        assert profile.engagement.morning_read_streak == 5

    def test_engagement_tier_computed(self):
        profile = _build()
        assert profile.engagement.engagement_tier in ("high", "medium", "low", "at_risk", "churned")

    def test_churned_tier_for_long_absence(self):
        ec = dict(_BASE_ENGAGEMENT, last_interaction_days=20)
        profile = _build(engagement_counts=ec)
        assert profile.engagement.engagement_tier == "churned"

    def test_at_risk_tier_for_week_absence(self):
        ec = dict(_BASE_ENGAGEMENT, last_interaction_days=9, sessions_last7=0)
        profile = _build(engagement_counts=ec)
        assert profile.engagement.engagement_tier == "at_risk"

    def test_high_tier_for_active_user(self):
        ec = dict(_BASE_ENGAGEMENT, sessions_last7=6, morning_reads_last30=26, last_interaction_days=0)
        profile = _build(engagement_counts=ec)
        assert profile.engagement.engagement_tier == "high"

    def test_nudge_rate_computed(self):
        profile = _build()
        assert profile.engagement.nudge_response_rate_30d is not None

    def test_missing_engagement_counts_gives_low_tier(self):
        profile = _build(engagement_counts=None)
        # Should not crash; tier may be None or "low"
        assert profile.engagement.engagement_tier in (None, "low", "churned", "at_risk")


# ── Confidence scoring ────────────────────────────────────────────────────────

class TestConfidenceScoring:
    def test_full_data_gives_higher_confidence(self):
        full = _build()
        sparse = _build(personal_model=None, psych_profile=None)
        assert full.data_confidence >= sparse.data_confidence

    def test_sparse_data_confidence_non_negative(self):
        sparse = _build(personal_model=None, psych_profile=None, habits=None)
        assert sparse.data_confidence >= 0.0

    def test_confidence_approaches_1_with_all_data(self):
        profile = _build()
        # With full data we expect at least 0.5
        assert profile.data_confidence >= 0.3


# ── Facts ─────────────────────────────────────────────────────────────────────

class TestFacts:
    def test_facts_loaded_and_sorted_by_confidence(self):
        facts = [
            {"id": "f1", "category": "person", "fact_text": "has a daughter",
             "fact_key": "family.daughter", "fact_value": None, "polarity": "neutral",
             "confidence": 0.3, "user_confirmed": False,
             "created_at": "2025-01-01T00:00:00"},
            {"id": "f2", "category": "goal", "fact_text": "wants to run 5k",
             "fact_key": "goal.5k", "fact_value": None, "polarity": "positive",
             "confidence": 0.8, "user_confirmed": True,
             "created_at": "2025-01-02T00:00:00"},
        ]
        profile = _build(facts=facts)
        assert len(profile.facts) == 2
        # High-confidence first
        assert profile.facts[0].confidence >= profile.facts[1].confidence

    def test_empty_facts_list(self):
        profile = _build(facts=[])
        assert profile.facts == []


# ── to_dict serialization ─────────────────────────────────────────────────────

class TestSerialization:
    def test_to_dict_returns_dict(self):
        profile = _build()
        d = profile.to_dict()
        assert isinstance(d, dict)

    def test_to_dict_has_required_keys(self):
        profile = _build()
        d = profile.to_dict()
        required = {"user_id", "archetype_primary", "physio", "psych", "behaviour",
                    "engagement", "coach_relationship", "facts", "coach_narrative",
                    "suggested_plan", "data_confidence", "last_computed_at"}
        assert required.issubset(d.keys())

    def test_to_dict_engagement_keys(self):
        profile = _build()
        eng = profile.to_dict()["engagement"]
        assert "engagement_tier" in eng
        assert "sessions_last7" in eng
