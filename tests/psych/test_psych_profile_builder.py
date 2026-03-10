"""
tests/psych/test_psych_profile_builder.py

Unit tests for psych/psych_profile_builder.py.

All tests are pure-Python — no DB, no async.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import pytest

from psych.psych_profile_builder import (
    _compute_discipline,
    _compute_interoception,
    _compute_mood_baseline,
    _infer_anxiety,
    _infer_activity_map,
    _infer_social_type,
    _pearson_r,
    build_psych_profile,
)
from psych.psych_schema import (
    AnxietyEventRecord,
    MoodRecord,
    PlanAdherence,
    PsychProfile,
    SocialEvent,
    TaggedActivityRecord,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _ts(offset_days: int = 0) -> datetime:
    from datetime import timedelta
    return datetime(2025, 1, 15, tzinfo=timezone.utc) - timedelta(days=offset_days)


def _social(before: float, after: float, day: int = 0) -> SocialEvent:
    return SocialEvent(
        recovery_score_before = before,
        recovery_score_after  = after,
        duration_minutes      = 60,
        event_id              = f"se-{day}",
        ts                    = _ts(day),
    )


def _activity(
    slug: str,
    kind: str,       # "recovery" | "stress"
    delta: float,
    count: int = 1,
) -> list[TaggedActivityRecord]:
    return [
        TaggedActivityRecord(
            slug               = slug,
            category           = kind,
            stress_or_recovery = kind,
            score_delta        = delta,
            duration_minutes   = 30,
            ts                 = _ts(i),
        )
        for i in range(count)
    ]


def _anxiety(trigger: str, severity: str, stress_score: float = 65.0) -> AnxietyEventRecord:
    return AnxietyEventRecord(
        trigger_type          = trigger,
        severity              = severity,
        stress_score_at_event = stress_score,
        event_id              = trigger,
        ts                    = _ts(0),
    )


def _mood(
    mood_score: float,
    readiness: Optional[float] = None,
    day: int = 0,
) -> MoodRecord:
    return MoodRecord(
        mood_score             = mood_score,
        energy_score           = None,
        anxiety_score          = None,
        social_desire          = None,
        readiness_score_at_log = readiness,
        ts                     = _ts(day),
    )


def _adherence(planned: int, completed: int, day: int = 0) -> PlanAdherence:
    from datetime import date, timedelta
    return PlanAdherence(
        plan_date = date(2025, 1, 15) - timedelta(days=day),
        planned   = planned,
        completed = completed,
    )

# ── Social energy type ─────────────────────────────────────────────────────────

class TestInferSocialType:
    def test_unknown_below_threshold(self):
        events = [_social(50, 60), _social(50, 58)]    # only 2
        stype, delta = _infer_social_type(events)
        assert stype == "unknown"
        assert delta == 0.0

    def test_extrovert_high_delta(self):
        events = [_social(40, 55), _social(45, 60), _social(42, 57)]
        stype, delta = _infer_social_type(events)
        assert stype == "extrovert"
        assert delta > 4.0

    def test_introvert_negative_delta(self):
        events = [_social(60, 50), _social(58, 48), _social(62, 52)]
        stype, delta = _infer_social_type(events)
        assert stype == "introvert"
        assert delta < -4.0

    def test_ambivert_small_delta(self):
        events = [_social(50, 52), _social(50, 49), _social(50, 51)]
        stype, delta = _infer_social_type(events)
        assert stype == "ambivert"
        assert -4.0 <= delta <= 4.0


# ── Anxiety inference ──────────────────────────────────────────────────────────

class TestInferAnxiety:
    def test_no_events_returns_zero_sensitivity_empty_triggers(self):
        sensitivity, triggers = _infer_anxiety([], [])
        assert sensitivity == 0.0
        assert triggers == []

    def test_sensitivity_from_stress_score(self):
        events = [_anxiety("deadline", "severe", stress_score=90.0)] * 3
        sensitivity, _ = _infer_anxiety(events, [])
        assert sensitivity == pytest.approx(0.9, abs=0.01)

    def test_triggers_ranked_by_strength(self):
        events = (
            [_anxiety("deadline",     "severe",   80.0)] * 5 +
            [_anxiety("confrontation","moderate", 60.0)] * 2 +
            [_anxiety("financial",    "mild",     40.0)] * 1
        )
        _, triggers = _infer_anxiety(events, [])
        assert len(triggers) > 0
        # Deadline should be #1 (most frequent + high severity)
        assert triggers[0].trigger_type == "deadline"
        # Strengths should be descending
        for i in range(len(triggers) - 1):
            assert triggers[i].strength >= triggers[i + 1].strength

    def test_top_5_limit(self):
        trigger_types = ["deadline", "confrontation", "financial",
                         "health_worry", "performance", "social_pressure", "crowds"]
        events = [_anxiety(t, "moderate", 60.0) for t in trigger_types for _ in range(3)]
        _, triggers = _infer_anxiety(events, [])
        assert len(triggers) <= 5

    def test_below_threshold_returns_empty_triggers(self):
        events = [_anxiety("deadline", "mild", 50.0)]   # only 1 → below min
        _, triggers = _infer_anxiety(events, [])
        assert triggers == []


# ── Activity map ───────────────────────────────────────────────────────────────

class TestInferActivityMap:
    def test_empty_returns_unknown_style(self):
        calming, stressing, style = _infer_activity_map([])
        assert calming == []
        assert stressing == []
        assert style == "unknown"

    def test_calming_activities_sorted_by_delta(self):
        acts = (
            _activity("nature_time", "recovery", 15.0, count=4) +
            _activity("meditation",  "recovery", 10.0, count=4) +
            _activity("cold_shower", "recovery", 20.0, count=4)
        )
        calming, _, _ = _infer_activity_map(acts)
        assert calming[0].slug == "cold_shower"
        assert calming[1].slug == "nature_time"

    def test_stressing_activities_sorted_by_abs_delta(self):
        acts = (
            _activity("work_sprint", "stress", -15.0, count=4) +
            _activity("commute",     "stress",  -5.0, count=4)
        )
        _, stressing, _ = _infer_activity_map(acts)
        assert stressing[0].slug == "work_sprint"

    def test_below_min_events_not_included(self):
        # Only 2 events — below _MIN_ACTIVITY_EVENTS=3
        acts = _activity("yoga", "recovery", 15.0, count=2)
        calming, _, _ = _infer_activity_map(acts)
        assert calming == []

    def test_recovery_style_mapped_from_slug(self):
        acts = _activity("social_time", "recovery", 12.0, count=4)
        _, _, style = _infer_activity_map(acts)
        assert style == "social"

    def test_recovery_style_physical_for_cold_shower(self):
        acts = _activity("cold_shower", "recovery", 18.0, count=4)
        _, _, style = _infer_activity_map(acts)
        assert style == "physical"


# ── Discipline index ───────────────────────────────────────────────────────────

class TestComputeDiscipline:
    def test_returns_zero_below_threshold(self):
        records = [_adherence(3, 3, i) for i in range(5)]    # only 5 days
        assert _compute_discipline(records) == 0.0

    def test_perfect_adherence(self):
        records = [_adherence(3, 3, i) for i in range(10)]
        score = _compute_discipline(records)
        assert score == 100.0

    def test_zero_adherence(self):
        records = [_adherence(3, 0, i) for i in range(10)]
        score = _compute_discipline(records)
        assert score == 0.0

    def test_partial_adherence(self):
        records = [_adherence(4, 2, i) for i in range(10)]
        score = _compute_discipline(records)
        assert 40.0 < score < 60.0

    def test_no_plans_gives_full_score(self):
        records = [_adherence(0, 0, i) for i in range(10)]
        score = _compute_discipline(records)
        assert score == 100.0

    def test_recent_days_weighted_higher(self):
        # Recent 5 days perfect, older 5 days zero
        older  = [_adherence(3, 0, i + 5) for i in range(5)]
        recent = [_adherence(3, 3, i)     for i in range(5)]
        score = _compute_discipline(older + recent)
        # Score should be above 50 because recent days get more weight
        assert score > 50.0


# ── Mood baseline ──────────────────────────────────────────────────────────────

class TestComputeMoodBaseline:
    def test_empty_returns_unknown(self):
        avg, label = _compute_mood_baseline([])
        assert avg is None
        assert label == "unknown"

    def test_high_mood(self):
        records = [_mood(4.0, day=i) for i in range(5)]
        avg, label = _compute_mood_baseline(records)
        assert label == "high"
        assert avg == pytest.approx(4.0)

    def test_moderate_mood(self):
        records = [_mood(3.0, day=i) for i in range(5)]
        avg, label = _compute_mood_baseline(records)
        assert label == "moderate"

    def test_low_mood(self):
        records = [_mood(1.5, day=i) for i in range(5)]
        avg, label = _compute_mood_baseline(records)
        assert label == "low"

    def test_uses_last_14_records(self):
        # 20 records: first 10 are high (5.0), last 10 are neutral (3.0)
        old    = [_mood(5.0, day=i + 10) for i in range(10)]
        recent = [_mood(3.0, day=i)      for i in range(10)]
        all_records = old + recent
        avg, label = _compute_mood_baseline(all_records)
        # Only last 14 used → mostly the recent neutral ones
        assert label == "moderate"


# ── Interoception alignment ────────────────────────────────────────────────────

class TestComputeInteroception:
    def test_below_threshold_returns_none(self):
        records = [_mood(3.0, 60.0, i) for i in range(5)]
        result = _compute_interoception(records)
        assert result is None

    def test_perfect_positive_correlation(self):
        scores = [40, 50, 60, 70, 80, 90, 100]
        records = [_mood(float(1 + i), float(s), i) for i, s in enumerate(scores)]
        r = _compute_interoception(records)
        assert r is not None
        assert r == pytest.approx(1.0, abs=0.01)

    def test_perfect_negative_correlation(self):
        mood_scores     = [5.0, 4.0, 3.0, 2.0, 1.0, 2.0, 3.0]
        readiness_scores = [20, 30, 40, 60, 80, 70, 50]
        records = [_mood(m, r, i) for i, (m, r) in enumerate(zip(mood_scores, readiness_scores))]
        r = _compute_interoception(records)
        assert r is not None
        assert r < 0.0

    def test_no_readiness_scores_returns_none(self):
        records = [_mood(3.0, None, i) for i in range(10)]
        result = _compute_interoception(records)
        assert result is None


# ── Pearson r ──────────────────────────────────────────────────────────────────

class TestPearsonR:
    def test_perfect_positive(self):
        xs = [1.0, 2.0, 3.0, 4.0, 5.0]
        ys = [2.0, 4.0, 6.0, 8.0, 10.0]
        assert _pearson_r(xs, ys) == pytest.approx(1.0, abs=1e-6)

    def test_perfect_negative(self):
        xs = [1.0, 2.0, 3.0]
        ys = [3.0, 2.0, 1.0]
        assert _pearson_r(xs, ys) == pytest.approx(-1.0, abs=1e-6)

    def test_no_variance_returns_none(self):
        xs = [3.0, 3.0, 3.0]
        ys = [5.0, 6.0, 7.0]
        assert _pearson_r(xs, ys) is None

    def test_too_few_points_returns_none(self):
        assert _pearson_r([1.0], [2.0]) is None


# ── build_psych_profile (integration) ─────────────────────────────────────────

class TestBuildPsychProfile:
    def test_empty_inputs_returns_unknown_profile(self):
        profile = build_psych_profile(
            social_events    = [],
            tagged_activities= [],
            anxiety_events   = [],
            mood_records     = [],
            plan_adherence   = [],
        )
        assert isinstance(profile, PsychProfile)
        assert profile.social_energy_type == "unknown"
        assert profile.mood_baseline == "unknown"
        assert profile.discipline_index == 0.0
        assert profile.data_confidence == 0.0
        assert profile.coach_insight is not None   # always returns a string

    def test_full_inputs_produce_valid_profile(self):
        social = [_social(40, 60, i) for i in range(5)]
        acts = (
            _activity("cold_shower",  "recovery", 18.0, count=5) +
            _activity("meditation",   "recovery", 12.0, count=4) +
            _activity("work_sprint",  "stress",  -14.0, count=5)
        )
        anxiety = [_anxiety("deadline", "severe", 80.0) for _ in range(4)]
        moods   = [_mood(float(3 + (i % 2)), 50.0 + i * 3, i) for i in range(10)]
        plans   = [_adherence(3, 3, i) for i in range(14)]

        profile = build_psych_profile(
            social_events     = social,
            tagged_activities = acts,
            anxiety_events    = anxiety,
            mood_records      = moods,
            plan_adherence    = plans,
            streak_current    = 7,
            streak_best       = 21,
        )

        assert profile.social_energy_type == "extrovert"
        assert profile.streak_current == 7
        assert profile.streak_best == 21
        assert profile.primary_recovery_style == "physical"
        assert profile.discipline_index == 100.0
        assert len(profile.top_anxiety_triggers) > 0
        assert profile.top_anxiety_triggers[0].trigger_type == "deadline"
        assert profile.data_confidence > 0.0

    def test_to_dict_serialisable(self):
        import json
        profile = build_psych_profile([], [], [], [], [])
        d = profile.to_dict()
        # Should not raise
        serialised = json.dumps(d)
        assert "social_energy_type" in serialised

    def test_coach_insight_is_string(self):
        profile = build_psych_profile([], [], [], [], [])
        assert isinstance(profile.coach_insight, str)
        assert len(profile.coach_insight) > 0


# ── Conversation extractor integration ────────────────────────────────────────

class TestConversationExtractorExtensions:
    def test_extracts_anxiety_trigger_deadline(self):
        from coach.conversation_extractor import extract_signals_from_message
        result = extract_signals_from_message(
            "I have a major deadline tomorrow and I'm really stressed"
        )
        assert result.anxiety_trigger_type == "deadline"

    def test_extracts_anxiety_trigger_confrontation(self):
        from coach.conversation_extractor import extract_signals_from_message
        result = extract_signals_from_message("Had a big argument with my manager today")
        assert result.anxiety_trigger_type == "confrontation"

    def test_extracts_mood_signal_positive(self):
        from coach.conversation_extractor import extract_signals_from_message
        result = extract_signals_from_message("Feeling great today, lots of energy")
        assert result.mood_signal is not None
        assert result.mood_signal.mood_score == 4.0
        assert result.mood_signal.energy_score == 5.0

    def test_extracts_mood_signal_negative(self):
        from coach.conversation_extractor import extract_signals_from_message
        result = extract_signals_from_message("terrible day, completely burned out and miserable")
        assert result.mood_signal is not None
        assert result.mood_signal.mood_score == 1.0

    def test_extracts_anxiety_in_mood_signal(self):
        from coach.conversation_extractor import extract_signals_from_message
        result = extract_signals_from_message("I am very anxious about the presentation")
        assert result.mood_signal is not None
        # "very anxious" matches HIGH pattern → score 5.0
        assert result.mood_signal.anxiety_score >= 3.0
        assert result.anxiety_trigger_type == "performance"

    def test_no_anxiety_trigger_on_neutral_message(self):
        from coach.conversation_extractor import extract_signals_from_message
        result = extract_signals_from_message("Had a relaxing evening at home")
        assert result.anxiety_trigger_type is None

    def test_no_mood_signal_on_factual_message(self):
        from coach.conversation_extractor import extract_signals_from_message
        result = extract_signals_from_message("I went for a run this morning")
        assert result.mood_signal is None
