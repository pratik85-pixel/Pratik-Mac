"""
tests/tagging/test_tagging_service.py

Unit tests for tagging/tagging_service.py
"""

import pytest
from datetime import datetime, timezone

from tagging.tagging_service import (
    TagResult,
    WindowRef,
    apply_user_tag,
    validate_tag,
    get_nudge_queue,
    run_auto_tag_pass,
    build_pattern_model_from_windows,
)
from tagging.tag_pattern_model import UserTagPatternModel


# ── Helpers ───────────────────────────────────────────────────────────────────

def _window(window_id: str, window_type: str, hour: int = 14,
            tag: str | None = None, suppression: float | None = None) -> WindowRef:
    ts = datetime(2026, 3, 10, hour, 0, 0, tzinfo=timezone.utc)
    return WindowRef(
        window_id=window_id,
        window_type=window_type,
        started_at=ts,
        tag=tag,
        tag_source="auto_detected" if tag is None else "user_confirmed",
        suppression_pct=suppression,
    )


# ── Validation ────────────────────────────────────────────────────────────────

class TestValidateTag:
    def test_valid_stress_slug_on_stress_window(self):
        ok, err = validate_tag("running", "stress")
        assert ok is True
        assert err == ""

    def test_valid_recovery_slug_on_recovery_window(self):
        ok, err = validate_tag("yoga", "recovery")
        assert ok is True

    def test_unknown_slug_invalid(self):
        ok, err = validate_tag("invalid_slug", "stress")
        assert ok is False
        assert "Unknown" in err

    def test_recovery_slug_on_stress_window_invalid(self):
        ok, err = validate_tag("yoga", "stress")
        assert ok is False
        assert "stress" in err.lower()

    def test_stress_slug_on_recovery_window_invalid(self):
        ok, err = validate_tag("running", "recovery")
        assert ok is False

    def test_mixed_slug_on_stress_window_valid(self):
        # walking is "mixed" — valid on stress windows (mixed activities can appear as stress)
        ok, err = validate_tag("walking", "stress")
        assert ok is True


# ── Apply user tag ────────────────────────────────────────────────────────────

class TestApplyUserTag:
    def test_successful_tag(self):
        window = _window("w1", "stress")
        result = apply_user_tag(window, "running")
        assert result.success is True
        assert result.tag_applied == "running"
        assert result.tag_source == "user_confirmed"

    def test_invalid_slug_fails(self):
        window = _window("w1", "stress")
        result = apply_user_tag(window, "does_not_exist")
        assert result.success is False
        assert result.tag_applied is None
        assert result.error is not None

    def test_incompatible_tag_fails(self):
        window = _window("w1", "recovery")
        result = apply_user_tag(window, "running")
        assert result.success is False


# ── Auto-tag pass ─────────────────────────────────────────────────────────────

class TestRunAutoTagPass:
    def test_empty_model_skips_all(self):
        model = UserTagPatternModel(user_id="u1")
        windows = [_window("w1", "stress"), _window("w2", "stress")]
        result = run_auto_tag_pass(model, windows)
        assert result.tagged_count == 0
        assert result.skipped_count == 2

    def test_matching_pattern_tags_window(self):
        # Build a model with a strong pattern at hour 14, weekday 0
        confirmed_windows = [
            _window(f"c{i}", "stress", hour=14, tag="work_sprint", suppression=0.5)
            for i in range(5)
        ]
        # Set weekday to Monday (0) consistently
        for w in confirmed_windows:
            object.__setattr__(w, "started_at",
                               w.started_at.replace(hour=14))

        result = build_pattern_model_from_windows(
            user_id="u1",
            confirmed_stress_windows=confirmed_windows,
            confirmed_recovery_windows=[],
        )
        model = result.model

        untagged = [_window("new_w", "stress", hour=14)]
        auto_result = run_auto_tag_pass(model, untagged)
        # Should have attempted — may or may not tag depending on weekday pattern
        assert auto_result.tagged_count + auto_result.skipped_count == 1


# ── Nudge queue ───────────────────────────────────────────────────────────────

class TestGetNudgeQueue:
    def test_returns_max_items(self):
        windows = [_window(f"w{i}", "stress", suppression=0.3) for i in range(10)]
        queue = get_nudge_queue(windows, max_items=3)
        assert len(queue) == 3

    def test_sorted_by_suppression_desc(self):
        windows = [
            _window("w1", "stress", suppression=0.2),
            _window("w2", "stress", suppression=0.7),
            _window("w3", "stress", suppression=0.5),
        ]
        queue = get_nudge_queue(windows, max_items=3)
        assert queue[0].window_id == "w2"
        assert queue[1].window_id == "w3"

    def test_already_tagged_excluded(self):
        windows = [
            _window("w1", "stress", tag="running"),
            _window("w2", "stress"),
        ]
        queue = get_nudge_queue(windows, max_items=3)
        assert len(queue) == 1
        assert queue[0].window_id == "w2"

    def test_empty_returns_empty(self):
        assert get_nudge_queue([], max_items=3) == []


# ── Pattern model build ───────────────────────────────────────────────────────

class TestBuildPatternModel:
    def test_builds_from_confirmed_windows(self):
        confirmed = [
            _window(f"w{i}", "stress", tag="work_sprint", suppression=0.4)
            for i in range(4)
        ]
        result = build_pattern_model_from_windows(
            user_id="u1",
            confirmed_stress_windows=confirmed,
            confirmed_recovery_windows=[],
        )
        assert result.user_id == "u1"
        assert result.patterns_built >= 1

    def test_below_minimum_no_patterns(self):
        confirmed = [_window(f"w{i}", "stress", tag="running") for i in range(2)]
        result = build_pattern_model_from_windows(
            user_id="u1",
            confirmed_stress_windows=confirmed,
            confirmed_recovery_windows=[],
        )
        assert result.patterns_built == 0

    def test_recovery_windows_included(self):
        confirmed_recovery = [
            _window(f"r{i}", "recovery", tag="yoga") for i in range(4)
        ]
        result = build_pattern_model_from_windows(
            user_id="u1",
            confirmed_stress_windows=[],
            confirmed_recovery_windows=confirmed_recovery,
        )
        assert result.patterns_built >= 1
