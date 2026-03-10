"""
tests/profile/test_fact_extractor.py

Unit tests for profile/fact_extractor.py.

All tests are pure-Python — no DB, no async.
"""

from __future__ import annotations

import pytest

from profile.fact_extractor import ExtractedFact, extract_facts, merge_with_existing


# ── Helpers ───────────────────────────────────────────────────────────────────

def _categories(facts: list[ExtractedFact]) -> list[str]:
    return [f.category for f in facts]


def _keys(facts: list[ExtractedFact]) -> list[str | None]:
    return [f.fact_key for f in facts]


# ── Person patterns ───────────────────────────────────────────────────────────

class TestPersonPatterns:
    def test_daughter_detected(self):
        facts = extract_facts("My daughter started school today.")
        assert any(f.category == "person" and "daughter" in (f.fact_key or "") for f in facts)

    def test_son_detected(self):
        facts = extract_facts("My son just turned 10.")
        assert any(f.category == "person" and "son" in (f.fact_key or "") for f in facts)

    def test_wife_detected(self):
        facts = extract_facts("My wife is stressed about work.")
        assert any(f.category == "person" and "wife" in (f.fact_key or "") for f in facts)

    def test_husband_detected(self):
        facts = extract_facts("My husband has been travelling a lot.")
        assert any(f.category == "person" and "husband" in (f.fact_key or "") for f in facts)

    def test_partner_detected(self):
        facts = extract_facts("My partner and I had an argument.")
        assert any(f.category == "person" and "partner" in (f.fact_key or "") for f in facts)

    def test_kids_detected(self):
        facts = extract_facts("The kids have been running me ragged.")
        assert any(f.category == "person" and "kids" in (f.fact_key or "") for f in facts)

    def test_parents_detected(self):
        facts = extract_facts("My mum is coming to visit this week.")
        assert any(f.category == "person" for f in facts)

    def test_work_friend_detected(self):
        facts = extract_facts("Had drinks with a friend from work.")
        assert any(f.category == "person" and "work_friend" in (f.fact_key or "") for f in facts)

    def test_empty_message_returns_empty(self):
        assert extract_facts("") == []

    def test_no_match_returns_empty(self):
        assert extract_facts("The weather is nice today.") == []


# ── Preference patterns ───────────────────────────────────────────────────────

class TestPreferencePatterns:
    def test_cold_shower_hate(self):
        facts = extract_facts("I hate cold showers, they're awful.")
        matches = [f for f in facts if f.fact_key == "activity.cold_shower"]
        assert matches
        assert matches[0].polarity == "negative"

    def test_cold_shower_like(self):
        facts = extract_facts("I love cold showers in the morning.")
        matches = [f for f in facts if f.fact_key == "activity.cold_shower"]
        assert matches
        assert matches[0].polarity == "positive"

    def test_no_meditation(self):
        facts = extract_facts("I don't meditate, it's not for me.")
        assert any(f.category == "preference" and "meditation" in (f.fact_key or "") for f in facts)

    def test_likes_nature(self):
        facts = extract_facts("I love being outdoors, it really helps me decompress.")
        assert any(f.category == "preference" and "nature" in (f.fact_key or "") for f in facts)

    def test_likes_music(self):
        facts = extract_facts("I enjoy listening to music when I'm stressed.")
        assert any(f.category == "preference" and "music" in (f.fact_key or "") for f in facts)

    def test_introvert_self_report(self):
        facts = extract_facts("I'm quite introverted, social stuff drains me.")
        assert any(f.category == "preference" for f in facts)

    def test_default_confidence_is_half(self):
        facts = extract_facts("I love cold showers.")
        assert all(abs(f.confidence - 0.5) < 0.01 for f in facts)


# ── Schedule patterns ─────────────────────────────────────────────────────────

class TestSchedulePatterns:
    def test_wfh_day_detected(self):
        facts = extract_facts("I work from home on Wednesdays.")
        assert any(f.category == "schedule" and "wfh" in (f.fact_key or "") for f in facts)

    def test_gym_day_detected(self):
        facts = extract_facts("I go to the gym on Tuesdays.")
        assert any(f.category == "schedule" and "gym" in (f.fact_key or "") for f in facts)

    def test_early_riser(self):
        facts = extract_facts("I'm an early riser, up at 5:30 most days.")
        assert any(f.category == "schedule" and "early_riser" in (f.fact_key or "") for f in facts)

    def test_night_owl(self):
        facts = extract_facts("I'm a night owl, rarely in bed before midnight.")
        assert any(f.category == "schedule" and "night_owl" in (f.fact_key or "") for f in facts)


# ── Event patterns ────────────────────────────────────────────────────────────

class TestEventPatterns:
    def test_presentation_detected(self):
        facts = extract_facts("I have a big presentation on Thursday.")
        assert any(f.category == "event" and "presentation" in (f.fact_key or "") for f in facts)

    def test_holiday_detected(self):
        facts = extract_facts("I'm going on holiday next week.")
        assert any(f.category == "event" for f in facts)

    def test_new_job_detected(self):
        facts = extract_facts("I just started a new job this month.")
        assert any(f.category == "event" and "new_job" in (f.fact_key or "") for f in facts)


# ── Goal patterns ─────────────────────────────────────────────────────────────

class TestGoalPatterns:
    def test_run_5k_detected(self):
        facts = extract_facts("I want to run a 5k by summer.")
        assert any(f.category == "goal" and "5k" in (f.fact_key or "") for f in facts)

    def test_lose_weight_detected(self):
        facts = extract_facts("I'm trying to lose weight this year.")
        assert any(f.category == "goal" for f in facts)

    def test_better_sleep_detected(self):
        facts = extract_facts("I really want to improve my sleep.")
        assert any(f.category == "goal" and "sleep" in (f.fact_key or "") for f in facts)


# ── Health patterns ───────────────────────────────────────────────────────────

class TestHealthPatterns:
    def test_migraines_detected(self):
        facts = extract_facts("I get migraines when I'm sleep deprived.")
        assert any(f.category == "health" and "migraine" in (f.fact_key or "") for f in facts)

    def test_bad_knees_detected(self):
        # bad_knees lives in preference patterns (fact_key="health.knees")
        facts = extract_facts("I have bad knees so I can't run.")
        assert any("knees" in (f.fact_key or "") for f in facts)

    def test_anxiety_diagnosed(self):
        facts = extract_facts("I've been diagnosed with anxiety.")
        assert any(f.category == "health" and "anxiety" in (f.fact_key or "") for f in facts)


# ── Confirmation bump ─────────────────────────────────────────────────────────

class TestConfirmationBump:
    def test_confirmation_bumps_confidence(self):
        facts = extract_facts("Yes exactly, I hate cold showers and I work from home on Fridays.")
        # at least one fact confidence should be elevated to 0.9
        assert any(abs(f.confidence - 0.9) < 0.01 for f in facts)

    def test_no_confirmation_keeps_base(self):
        facts = extract_facts("I hate cold showers.")
        assert all(abs(f.confidence - 0.5) < 0.01 for f in facts)


# ── merge_with_existing ───────────────────────────────────────────────────────

class TestMergeWithExisting:
    def _make_fact(self, category: str, key: str, text: str) -> ExtractedFact:
        return ExtractedFact(
            category=category,
            fact_text=text,
            fact_key=key,
            fact_value=None,
            polarity="neutral",
            confidence=0.5,
        )

    def test_new_fact_added(self):
        extracted = [self._make_fact("person", "family.daughter", "has a daughter")]
        new_facts, update_ids = merge_with_existing(extracted, [])
        assert len(new_facts) == 1
        assert update_ids == []

    def test_duplicate_key_not_re_added(self):
        existing = [
            {"id": "abc-123", "category": "person", "fact_key": "family.daughter"}
        ]
        extracted = [self._make_fact("person", "family.daughter", "my daughter is Aria")]
        new_facts, update_ids = merge_with_existing(extracted, existing)
        assert new_facts == []
        assert "abc-123" in update_ids

    def test_different_key_is_not_duplicate(self):
        existing = [
            {"id": "son-1", "category": "person", "fact_key": "family.son"}
        ]
        extracted = [self._make_fact("person", "family.daughter", "has a daughter")]
        new_facts, update_ids = merge_with_existing(extracted, existing)
        assert len(new_facts) == 1
        assert update_ids == []

    def test_multiple_facts_partially_overlap(self):
        existing = [
            {"id": "cold-1", "category": "preference", "fact_key": "activity.cold_shower"}
        ]
        extracted = [
            self._make_fact("preference", "activity.cold_shower", "hate cold showers"),
            self._make_fact("goal", "goal.5k", "wants to run a 5k"),
        ]
        new_facts, update_ids = merge_with_existing(extracted, existing)
        assert len(new_facts) == 1  # only the goal is new
        assert "cold-1" in update_ids

    def test_null_fact_key_never_deduplicates(self):
        """Facts without a fact_key are always treated as new."""
        existing = [{"id": "x-1", "category": "event", "fact_key": None}]
        extracted = [
            ExtractedFact(
                category="event", fact_text="big presentation",
                fact_key=None, fact_value=None, polarity="neutral",
            )
        ]
        new_facts, update_ids = merge_with_existing(extracted, existing)
        assert len(new_facts) == 1
        assert update_ids == []
