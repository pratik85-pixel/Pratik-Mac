"""
tests/tagging/test_auto_tagger.py

Unit tests for tagging/auto_tagger.py
"""

import pytest

from tagging.auto_tagger import (
    AUTO_TAG_THRESHOLD,
    AUTOTAG_MIN_CONFIRMED,
    TagEvent,
    build_patterns,
    suggest_tag,
    _hour_score,
    _weekday_score,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_events(slug: str, hour: int, weekday: int, count: int, window_type: str = "stress"):
    """Generate `count` identical events for a given slug."""
    return [
        TagEvent(hour=hour, weekday=weekday, tag=slug, window_type=window_type)
        for _ in range(count)
    ]


class TestBuildPatterns:
    def test_below_minimum_excluded(self):
        events = _make_events("work_sprint", hour=10, weekday=1, count=AUTOTAG_MIN_CONFIRMED - 1)
        patterns = build_patterns(events)
        assert "work_sprint" not in patterns

    def test_at_minimum_included(self):
        events = _make_events("work_sprint", hour=10, weekday=1, count=AUTOTAG_MIN_CONFIRMED)
        patterns = build_patterns(events)
        assert "work_sprint" in patterns

    def test_confirmed_count_correct(self):
        events = _make_events("running", hour=7, weekday=0, count=6)
        patterns = build_patterns(events)
        assert patterns["running"].confirmed_count == 6

    def test_hour_histogram_populated(self):
        events = _make_events("running", hour=7, weekday=0, count=5)
        patterns = build_patterns(events)
        assert patterns["running"].hour_histogram.get(7, 0) == 5

    def test_weekday_counts_populated(self):
        events = _make_events("running", hour=7, weekday=2, count=4)
        patterns = build_patterns(events)
        assert patterns["running"].weekday_counts.get(2, 0) == 4

    def test_mixed_events_two_slugs(self):
        events = (
            _make_events("running", hour=7, weekday=0, count=4) +
            _make_events("work_sprint", hour=14, weekday=1, count=4)
        )
        patterns = build_patterns(events)
        assert "running" in patterns
        assert "work_sprint" in patterns

    def test_events_without_tag_ignored(self):
        events = [TagEvent(hour=10, weekday=1, tag=None, window_type="stress")] * 5
        patterns = build_patterns(events)
        assert len(patterns) == 0

    def test_avg_suppression_calculated(self):
        events = [
            TagEvent(hour=10, weekday=1, tag="work_sprint", window_type="stress", suppression_pct=0.4),
            TagEvent(hour=10, weekday=1, tag="work_sprint", window_type="stress", suppression_pct=0.6),
            TagEvent(hour=10, weekday=1, tag="work_sprint", window_type="stress", suppression_pct=0.5),
        ]
        patterns = build_patterns(events)
        assert patterns["work_sprint"].avg_suppression == pytest.approx(0.5, abs=0.01)


class TestSuggestTag:
    def test_returns_best_tag_above_threshold(self):
        events = _make_events("work_sprint", hour=14, weekday=1, count=5)
        patterns = build_patterns(events)
        candidate = TagEvent(hour=14, weekday=1, tag=None, window_type="stress")
        result = suggest_tag(candidate, patterns)
        assert result.best_tag == "work_sprint"
        assert result.eligible is True
        assert result.confidence >= AUTO_TAG_THRESHOLD

    def test_wrong_window_type_returns_zero_score(self):
        events = _make_events("yoga", hour=20, weekday=3, count=5, window_type="recovery")
        patterns = build_patterns(events)
        # Candidate is stress, pattern is recovery
        candidate = TagEvent(hour=20, weekday=3, tag=None, window_type="stress")
        result = suggest_tag(candidate, patterns)
        assert result.all_scores.get("yoga", 0.0) == 0.0

    def test_empty_patterns_returns_none(self):
        candidate = TagEvent(hour=14, weekday=1, tag=None, window_type="stress")
        result = suggest_tag(candidate, {})
        assert result.best_tag is None
        assert result.eligible is False

    def test_different_hour_reduces_confidence(self):
        events = _make_events("work_sprint", hour=14, weekday=1, count=5)
        patterns = build_patterns(events)
        # Far-off hour
        candidate = TagEvent(hour=22, weekday=1, tag=None, window_type="stress")
        result = suggest_tag(candidate, patterns)
        assert result.confidence < AUTO_TAG_THRESHOLD or result.all_scores.get("work_sprint", 1.0) < 0.9


class TestHourScore:
    def test_exact_match_scores_high(self):
        histogram = {14: 5}
        score = _hour_score(14, histogram)
        assert score == pytest.approx(1.0, abs=0.01)

    def test_within_band_scores_positive(self):
        histogram = {14: 5}
        score = _hour_score(15, histogram)
        assert 0.0 < score < 1.0

    def test_outside_band_scores_zero(self):
        from tagging.auto_tagger import HOUR_BAND_WIDTH
        histogram = {14: 5}
        score = _hour_score(14 + HOUR_BAND_WIDTH + 3, histogram)
        assert score == 0.0

    def test_empty_histogram_returns_zero(self):
        assert _hour_score(10, {}) == 0.0


class TestWeekdayScore:
    def test_exact_match_max_score(self):
        counts = {1: 5}
        score = _weekday_score(1, counts)
        assert score == pytest.approx(1.0, abs=0.01)

    def test_no_match_returns_zero(self):
        counts = {1: 5}
        score = _weekday_score(5, counts)
        assert score == 0.0

    def test_mixed_weekdays_partial_score(self):
        counts = {1: 3, 3: 2}  # 3/5 = 0.6 for weekday 1
        score = _weekday_score(1, counts)
        assert score == pytest.approx(0.6, abs=0.01)
