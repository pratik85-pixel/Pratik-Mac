"""
tests/coach/test_conversation_extractor_lifestyle.py

Tests for lifestyle activity extraction added to conversation_extractor.py
(sports, social, cold shower, entertainment, nature patterns).
"""

import pytest

from coach.conversation_extractor import extract_signals_from_message


class TestSportsExtraction:
    def test_tennis_game(self):
        result = extract_signals_from_message("I played tennis last night")
        types = [s.event_type for s in result.signals]
        assert "sports_activity" in types

    def test_pickleball(self):
        result = extract_signals_from_message("went to play pickleball this morning")
        types = [s.event_type for s in result.signals]
        assert "sports_activity" in types

    def test_basketball(self):
        result = extract_signals_from_message("played basketball after work")
        types = [s.event_type for s in result.signals]
        assert "sports_activity" in types

    def test_intense_game_heavy(self):
        result = extract_signals_from_message("had a really intense competitive match last night")
        signals = [s for s in result.signals if s.event_type == "sports_activity"]
        assert len(signals) >= 1

    def test_no_sport_keywords_no_signal(self):
        result = extract_signals_from_message("I had a great day at work")
        types = [s.event_type for s in result.signals]
        assert "sports_activity" not in types


class TestSocialExtraction:
    def test_went_out_with_friends(self):
        result = extract_signals_from_message("went out with friends last night")
        types = [s.event_type for s in result.signals]
        assert "social_time" in types

    def test_dinner_out(self):
        result = extract_signals_from_message("had dinner out with my partner")
        types = [s.event_type for s in result.signals]
        assert "social_time" in types

    def test_drinks_with(self):
        result = extract_signals_from_message("drinks with colleagues after work")
        types = [s.event_type for s in result.signals]
        # May also capture alcohol
        assert "social_time" in types or "alcohol" in types

    def test_party_is_moderate(self):
        result = extract_signals_from_message("had a big night out at a party")
        social_signals = [s for s in result.signals if s.event_type == "social_time"]
        assert len(social_signals) >= 1
        assert social_signals[0].severity in ("moderate", "heavy")


class TestColdShowerExtraction:
    def test_cold_shower(self):
        result = extract_signals_from_message("took a cold shower this morning")
        types = [s.event_type for s in result.signals]
        assert "cold_shower" in types

    def test_cold_plunge(self):
        result = extract_signals_from_message("did a cold plunge yesterday")
        types = [s.event_type for s in result.signals]
        assert "cold_shower" in types

    def test_ice_bath(self):
        result = extract_signals_from_message("tried an ice bath after my workout")
        types = [s.event_type for s in result.signals]
        assert "cold_shower" in types

    def test_no_false_positive(self):
        result = extract_signals_from_message("had a warm shower and felt relaxed")
        types = [s.event_type for s in result.signals]
        assert "cold_shower" not in types


class TestEntertainmentExtraction:
    def test_watched_movie(self):
        result = extract_signals_from_message("watched a movie last night")
        types = [s.event_type for s in result.signals]
        assert "entertainment" in types

    def test_netflix(self):
        result = extract_signals_from_message("did some Netflix after dinner")
        types = [s.event_type for s in result.signals]
        assert "entertainment" in types

    def test_binge_watching(self):
        result = extract_signals_from_message("binge-watched a TV show")
        types = [s.event_type for s in result.signals]
        assert "entertainment" in types

    def test_gaming(self):
        result = extract_signals_from_message("played video games for a couple of hours")
        types = [s.event_type for s in result.signals]
        assert "entertainment" in types


class TestNatureExtraction:
    def test_walk_in_nature(self):
        result = extract_signals_from_message("went for a walk in the park")
        types = [s.event_type for s in result.signals]
        assert "nature_time" in types

    def test_park_run(self):
        result = extract_signals_from_message("did my parkrun this morning")
        types = [s.event_type for s in result.signals]
        assert "nature_time" in types

    def test_fresh_air(self):
        result = extract_signals_from_message("got some fresh air outside this afternoon")
        types = [s.event_type for s in result.signals]
        assert "nature_time" in types

    def test_hiking(self):
        result = extract_signals_from_message("went on a hike with family yesterday")
        types = [s.event_type for s in result.signals]
        assert "nature_time" in types


class TestNoRegressionExistingPatterns:
    """Ensure the new patterns don't break existing signal extraction."""

    def test_alcohol_still_extracted(self):
        result = extract_signals_from_message("had a few drinks last night")
        types = [s.event_type for s in result.signals]
        assert "alcohol" in types

    def test_stress_still_extracted(self):
        result = extract_signals_from_message("feeling really stressed about work")
        types = [s.event_type for s in result.signals]
        assert "stressful_event" in types

    def test_no_signals_returns_empty(self):
        result = extract_signals_from_message("everything is normal today")
        assert result.signals == []

    def test_duplicate_signals_not_added_twice(self):
        # existing_signals uses the internal key format: "{event_type}_{severity}_{hours}h"
        # "played tennis last night" → hours_ago≈8 (last night), severity=moderate
        existing = ["sports_activity_moderate_8h"]
        result = extract_signals_from_message("played tennis last night", existing_signals=existing)
        new_types = [s.event_type for s in result.signals]
        assert "sports_activity" not in new_types
