"""
tests/tagging/test_activity_catalog.py

Unit tests for tagging/activity_catalog.py
"""

import pytest

from tagging.activity_catalog import (
    CATALOG,
    COACH_FOLLOW_UP_SLUGS,
    MOVEMENT_SLUGS,
    RECOVERY_SLUGS,
    get_activity,
    get_display,
    is_recovery_activity,
    is_valid_slug,
    needs_coach_follow_up,
    slugs_for_category,
)


class TestCatalogPresence:
    """All design-specified slugs must exist in the catalog."""

    _required_slugs = [
        "running", "weight_training", "cycling", "swimming", "walking",
        "hiking", "sports",
        "coherence_breathing",
        "meditation", "journaling",
        "book_reading", "music", "social_time", "entertainment",
        "yoga", "cold_shower", "nature_time",
        "nap", "sleep",
        "work_sprint", "commute",
    ]

    @pytest.mark.parametrize("slug", _required_slugs)
    def test_slug_in_catalog(self, slug):
        assert slug in CATALOG, f"Missing slug: {slug}"

    def test_unique_slugs(self):
        """All slugs must be unique."""
        from tagging.activity_catalog import _CATALOG as raw
        slugs = [a.slug for a in raw]
        assert len(slugs) == len(set(slugs)), "Duplicate slug detected"


class TestActivityDefinitionFields:
    def test_get_activity_returns_correct_type(self):
        act = get_activity("running")
        assert act is not None
        assert act.slug == "running"
        assert act.category == "movement"
        assert act.stress_or_recovery == "stress"

    def test_get_activity_unknown_returns_none(self):
        assert get_activity("nonexistent_slug") is None

    def test_is_valid_slug(self):
        assert is_valid_slug("walking") is True
        assert is_valid_slug("does_not_exist") is False

    def test_get_display(self):
        assert get_display("running") == "Running"
        assert get_display("coherence_breathing") == "ZenFlow session"
        assert get_display("unknown_slug", fallback="Unknown") == "Unknown"


class TestCatalogProperties:
    def test_cold_shower_in_catalog(self):
        act = get_activity("cold_shower")
        assert act is not None
        assert act.category == "recovery_active"
        assert act.stress_or_recovery == "recovery"

    def test_social_time_no_sensor_signal(self):
        act = get_activity("social_time")
        assert act is not None
        assert len(act.evidence_signals) == 0
        assert act.coach_follow_up is True

    def test_entertainment_no_sensor_signal(self):
        act = get_activity("entertainment")
        assert act is not None
        assert act.coach_follow_up is True

    def test_sports_is_prescribable_movement(self):
        act = get_activity("sports")
        assert act is not None
        assert act.category == "movement"
        assert act.prescribable is True

    def test_nature_time_is_recovery(self):
        act = get_activity("nature_time")
        assert act is not None
        assert act.stress_or_recovery == "recovery"
        assert act.recoverable is True

    def test_sleep_not_prescribable(self):
        act = get_activity("sleep")
        assert act is not None
        assert act.prescribable is False

    def test_coherence_breathing_requires_session(self):
        act = get_activity("coherence_breathing")
        assert act is not None
        assert act.requires_session is True


class TestHelperFunctions:
    def test_is_recovery_activity(self):
        assert is_recovery_activity("yoga") is True
        assert is_recovery_activity("cold_shower") is True
        assert is_recovery_activity("running") is False

    def test_is_movement_activity(self):
        from tagging.activity_catalog import is_movement_activity
        assert is_movement_activity("running") is True
        assert is_movement_activity("yoga") is False

    def test_needs_coach_follow_up(self):
        assert needs_coach_follow_up("social_time") is True
        assert needs_coach_follow_up("entertainment") is True
        assert needs_coach_follow_up("cold_shower") is True
        assert needs_coach_follow_up("running") is False

    def test_slugs_for_category(self):
        movement_slugs = slugs_for_category("movement")
        assert "running" in movement_slugs
        assert "sports" in movement_slugs
        assert "yoga" not in movement_slugs

    def test_recovery_slugs_set(self):
        assert "yoga" in RECOVERY_SLUGS
        assert "cold_shower" in RECOVERY_SLUGS
        assert "social_time" in RECOVERY_SLUGS
        assert "entertainment" in RECOVERY_SLUGS
        assert "running" not in RECOVERY_SLUGS

    def test_coach_follow_up_slugs_set(self):
        assert "social_time" in COACH_FOLLOW_UP_SLUGS
        assert "entertainment" in COACH_FOLLOW_UP_SLUGS
        assert "cold_shower" in COACH_FOLLOW_UP_SLUGS
        assert "running" not in COACH_FOLLOW_UP_SLUGS
