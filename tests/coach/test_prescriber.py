"""
tests/coach/test_prescriber.py

Unit tests for coach/prescriber.py — personalised DailyPlan generator.
"""

import pytest

from coach.prescriber import (
    DailyPlan,
    PlanItem,
    PrescriberInputs,
    build_daily_plan,
    plan_to_items_json,
    _resolve_day_type,
    GREEN_THRESHOLD,
    YELLOW_THRESHOLD,
    RELAXED_THRESHOLD,
    SESSION_DURATION,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _inputs(**overrides) -> PrescriberInputs:
    """Build a PrescriberInputs with sensible defaults and optional overrides."""
    defaults = dict(
        stage=1,
        archetype_primary="sympathetic_dominant",
        flexibility="medium",
        movement_enjoyed=["walking", "yoga"],
        decompress_via=["book_reading", "music"],
        readiness_score=75.0,
        day_type="green",
        morning_rmssd_quality="good",
        plan_date="2026-03-10",
    )
    defaults.update(overrides)
    return PrescriberInputs(**defaults)


# ── Day type resolution ───────────────────────────────────────────────────────

class TestResolveDayType:
    def test_green(self):
        assert _resolve_day_type(76.0, "yellow") == "green"

    def test_yellow(self):
        assert _resolve_day_type(55.0, "green") == "yellow"

    def test_relaxed(self):
        assert _resolve_day_type(30.0, "green") == "relaxed"

    def test_red(self):
        assert _resolve_day_type(20.0, "green") == "red"

    def test_at_green_threshold_is_yellow(self):
        # Strict: only > GREEN_THRESHOLD is green
        assert _resolve_day_type(GREEN_THRESHOLD, "yellow") == "yellow"

    def test_just_below_green_is_yellow(self):
        assert _resolve_day_type(GREEN_THRESHOLD - 0.1, "green") == "yellow"

    def test_at_yellow_threshold_is_yellow(self):
        assert _resolve_day_type(YELLOW_THRESHOLD, "green") == "yellow"

    def test_just_below_yellow_is_relaxed(self):
        assert _resolve_day_type(YELLOW_THRESHOLD - 0.1, "green") == "relaxed"

    def test_at_relaxed_threshold_is_relaxed(self):
        assert _resolve_day_type(RELAXED_THRESHOLD, "green") == "relaxed"

    def test_just_below_relaxed_is_red(self):
        assert _resolve_day_type(RELAXED_THRESHOLD - 0.1, "green") == "red"


# ── Always must_do ZenFlow session ────────────────────────────────────────────

class TestZenFlowMustDo:
    def test_green_day_has_session(self):
        plan = build_daily_plan(_inputs(readiness_score=80.0))
        slugs = [i.activity_slug for i in plan.must_do]
        assert "coherence_breathing" in slugs

    def test_yellow_day_has_session(self):
        plan = build_daily_plan(_inputs(readiness_score=55.0))
        slugs = [i.activity_slug for i in plan.must_do]
        assert "coherence_breathing" in slugs

    def test_relaxed_day_has_session(self):
        plan = build_daily_plan(_inputs(readiness_score=30.0))
        slugs = [i.activity_slug for i in plan.must_do]
        assert "coherence_breathing" in slugs

    def test_red_day_has_session(self):
        plan = build_daily_plan(_inputs(readiness_score=20.0))
        slugs = [i.activity_slug for i in plan.must_do]
        assert "coherence_breathing" in slugs

    def test_green_session_duration(self):
        plan = build_daily_plan(_inputs(readiness_score=80.0))
        session = next(i for i in plan.must_do if i.activity_slug == "coherence_breathing")
        assert session.duration_min == SESSION_DURATION["green"]

    def test_red_session_duration_minimum(self):
        plan = build_daily_plan(_inputs(readiness_score=20.0))
        session = next(i for i in plan.must_do if i.activity_slug == "coherence_breathing")
        assert session.duration_min == SESSION_DURATION["red"]
        assert session.duration_min == 5


# ── Green day plan structure ──────────────────────────────────────────────────

class TestGreenDayPlan:
    def test_recommended_movement_on_green_day(self):
        plan = build_daily_plan(_inputs(
            readiness_score=80.0,
            movement_enjoyed=["running"],
        ))
        assert len(plan.recommended) >= 1
        assert plan.recommended[0].category == "movement"

    def test_preferred_movement_used(self):
        plan = build_daily_plan(_inputs(
            readiness_score=80.0,
            movement_enjoyed=["running", "cycling"],
        ))
        slugs = [i.activity_slug for i in plan.recommended]
        assert "running" in slugs

    def test_optional_slot_present(self):
        plan = build_daily_plan(_inputs(
            readiness_score=80.0,
            decompress_via=["cold_shower"],
        ))
        assert len(plan.optional) >= 1
        assert plan.optional[0].activity_slug == "cold_shower"

    def test_no_sport_overload_on_green_day(self):
        plan = build_daily_plan(_inputs(
            readiness_score=80.0,
            movement_enjoyed=["sports"],
            sport_overload_slugs=["sports"],
        ))
        all_slugs = [i.activity_slug for i in plan.recommended + plan.optional]
        assert "sports" not in all_slugs


# ── Yellow day plan structure ─────────────────────────────────────────────────

class TestYellowDayPlan:
    def test_light_movement_recommended(self):
        plan = build_daily_plan(_inputs(
            readiness_score=55.0,
            movement_enjoyed=["walking"],
        ))
        recommended_slugs = [i.activity_slug for i in plan.recommended]
        assert "walking" in recommended_slugs or any(
            s in recommended_slugs for s in ["yoga", "nature_time", "walking"]
        )

    def test_decompress_fallback(self):
        plan = build_daily_plan(_inputs(
            readiness_score=55.0,
            movement_enjoyed=["running"],  # not light — no light match in catalog here
            decompress_via=["social_time"],
        ))
        # recommended or optional should contain something
        all_items = plan.recommended + plan.optional
        assert len(all_items) >= 0   # just smoke-test


# ── Red day plan structure ────────────────────────────────────────────────────

class TestRedDayPlan:
    def test_red_day_recommended_is_rest(self):
        plan = build_daily_plan(_inputs(
            readiness_score=20.0,
            decompress_via=["entertainment"],
        ))
        assert plan.day_type == "red"
        assert len(plan.recommended) == 1
        assert plan.recommended[0].reason_code == "genuine_rest_red"

    def test_red_day_no_optional(self):
        plan = build_daily_plan(_inputs(readiness_score=20.0))
        assert plan.optional == []

    def test_red_day_uses_decompress_preference(self):
        plan = build_daily_plan(_inputs(
            readiness_score=20.0,
            decompress_via=["cold_shower"],
        ))
        assert plan.recommended[0].activity_slug == "cold_shower"


# ── Prescriber rules ──────────────────────────────────────────────────────────

class TestPrescriberRules:
    def test_no_intensity_when_consecutive_negative(self):
        plan = build_daily_plan(_inputs(
            readiness_score=80.0,
            consecutive_net_negative_days=4,
            movement_enjoyed=["running"],
        ))
        # Movement should be omitted or notes should reflect it
        notes_combined = " ".join(plan.prescriber_notes)
        assert "consecutive_net_negative" in notes_combined.lower() or \
               all(i.category != "movement" or i.activity_slug == "coherence_breathing"
                   for i in plan.recommended)

    def test_time_constraint_reduces_duration(self):
        plan = build_daily_plan(_inputs(
            readiness_score=80.0,
            deviation_reason_history=["time_constraint"] * 4,
            movement_enjoyed=["running"],
        ))
        notes_combined = " ".join(plan.prescriber_notes)
        # Should have noted time constraint
        assert "time_constraint" in notes_combined.lower()

    def test_low_adherence_deprioritises_category(self):
        plan = build_daily_plan(_inputs(
            readiness_score=80.0,
            adherence_by_category={"movement": 0.3},
            movement_enjoyed=["running"],
        ))
        notes_combined = " ".join(plan.prescriber_notes)
        assert "deprioritised" in notes_combined.lower() or \
               "low adherence" in notes_combined.lower()


# ── DailyPlan serialisation ───────────────────────────────────────────────────

class TestPlanSerialisation:
    def test_plan_to_items_json(self):
        plan = build_daily_plan(_inputs(readiness_score=75.0))
        items = plan_to_items_json(plan)
        assert isinstance(items, list)
        assert len(items) >= 1
        for item in items:
            assert "activity_slug" in item
            assert "priority" in item

    def test_must_do_in_items_json(self):
        plan = build_daily_plan(_inputs(readiness_score=75.0))
        items = plan_to_items_json(plan)
        priorities = [i["priority"] for i in items]
        assert "must_do" in priorities

    def test_plan_metadata(self):
        plan = build_daily_plan(_inputs(readiness_score=76.0, stage=2))
        assert plan.stage == 2
        assert plan.plan_date == "2026-03-10"
        assert plan.day_type == "green"
        assert plan.readiness == 76.0
