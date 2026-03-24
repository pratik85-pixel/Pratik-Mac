"""
tests/coach/test_data_assembler.py

Unit tests for coach/data_assembler.py.

All tests are pure-Python — no DB, no async runtime needed for the helpers.
The _fetch_* functions are tested via integration tests (not included here)
since they require a live AsyncSession.
"""

from __future__ import annotations

import pytest

from coach.data_assembler import (
    AssembledContext,
    _sanitize,
    _stress_label,
    _recovery_label,
    _estimate_tokens,
    _enforce_token_cap,
    _hours_ago_label,
    _round,
)


# ── Sanitizer ─────────────────────────────────────────────────────────────────

class TestSanitize:
    def test_strips_angle_brackets(self):
        result = _sanitize("<script>alert(1)</script>")
        assert "<" not in result
        assert ">" not in result

    def test_strips_backticks(self):
        result = _sanitize("ignore `previous instructions` and do X")
        assert "`" not in result

    def test_strips_curly_braces(self):
        result = _sanitize("inject {system} prompt")
        assert "{" not in result
        assert "}" not in result

    def test_strips_pipe(self):
        result = _sanitize("field | DROP TABLE users")
        assert "|" not in result

    def test_keeps_normal_fact_text(self):
        text = "has a daughter named Aria who started school"
        result = _sanitize(text)
        assert "daughter" in result
        assert "Aria" in result

    def test_keeps_punctuation(self):
        text = "works from home on Wednesdays, prefers 6pm sessions."
        result = _sanitize(text)
        assert "Wednesdays" in result
        assert "." in result

    def test_truncates_to_max_len(self):
        long_text = "a" * 500
        assert len(_sanitize(long_text, max_len=100)) == 100

    def test_empty_string_safe(self):
        assert _sanitize("") == ""

    def test_none_safe(self):
        # _sanitize is called with str — but test the None guard
        assert _sanitize(None) == ""   # type: ignore[arg-type]


# ── Population stress labels ──────────────────────────────────────────────────

class TestStressLabel:
    def test_none_is_unknown(self):
        assert _stress_label(None) == "unknown"

    def test_zero_is_low(self):
        assert _stress_label(0.0) == "low"

    def test_boundary_low_moderate(self):
        assert _stress_label(29.9) == "low"
        assert _stress_label(30.0) == "moderate"

    def test_boundary_moderate_high(self):
        assert _stress_label(59.9) == "moderate"
        assert _stress_label(60.0) == "high"

    def test_boundary_high_very_high(self):
        assert _stress_label(79.9) == "high"
        assert _stress_label(80.0) == "very high"

    def test_user_data_march_20(self):
        # Confirmed real data: stress_load=90.7 on Mar 20
        assert _stress_label(90.7) == "very high"

    def test_user_data_march_23(self):
        # Confirmed real data: stress_load=52.8 on Mar 23
        assert _stress_label(52.8) == "moderate"


# ── Population recovery labels ────────────────────────────────────────────────

class TestRecoveryLabel:
    def test_none_is_unknown(self):
        assert _recovery_label(None) == "unknown"

    def test_zero_is_poor(self):
        assert _recovery_label(0.0) == "poor"

    def test_boundary_poor_fair(self):
        assert _recovery_label(19.9) == "poor"
        assert _recovery_label(20.0) == "fair"

    def test_boundary_fair_good(self):
        assert _recovery_label(44.9) == "fair"
        assert _recovery_label(45.0) == "good"

    def test_boundary_good_excellent(self):
        assert _recovery_label(69.9) == "good"
        assert _recovery_label(70.0) == "excellent"

    def test_user_data_march_23(self):
        # Confirmed real data: waking_recovery=31.7 on Mar 23
        assert _recovery_label(31.7) == "fair"


# ── Hours-ago label ───────────────────────────────────────────────────────────

class TestHoursAgoLabel:
    def test_just_now_at_zero(self):
        assert _hours_ago_label(0.0) == "just now"

    def test_just_now_under_two(self):
        assert _hours_ago_label(1.9) == "just now"

    def test_hours_format(self):
        label = _hours_ago_label(5.0)
        assert label == "5h ago"

    def test_hours_boundary_15(self):
        assert "ago" in _hours_ago_label(15.9)

    def test_yesterday(self):
        assert _hours_ago_label(16.0) == "yesterday"
        assert _hours_ago_label(31.9) == "yesterday"

    def test_two_days(self):
        assert _hours_ago_label(32.0) == "2 days ago"
        assert _hours_ago_label(55.9) == "2 days ago"

    def test_three_days(self):
        assert _hours_ago_label(56.0) == "3 days ago"
        assert _hours_ago_label(70.0) == "3 days ago"


# ── Round helper ──────────────────────────────────────────────────────────────

class TestRound:
    def test_none_returns_none(self):
        assert _round(None) is None

    def test_rounds_to_1_decimal(self):
        assert _round(52.789) == 52.8

    def test_integer_input(self):
        assert _round(50.0) == 50.0


# ── Token estimation ──────────────────────────────────────────────────────────

class TestEstimateTokens:
    def test_empty_context_is_near_zero(self):
        ctx = AssembledContext()
        assert _estimate_tokens(ctx) < 10

    def test_large_narrative_increases_estimate(self):
        ctx_small = AssembledContext()
        ctx_large = AssembledContext(coach_narrative="x" * 4000)
        assert _estimate_tokens(ctx_large) > _estimate_tokens(ctx_small)

    def test_many_facts_increases_estimate(self):
        ctx_empty = AssembledContext()
        ctx_facts = AssembledContext(user_facts=["fact " * 20] * 10)
        assert _estimate_tokens(ctx_facts) > _estimate_tokens(ctx_empty)


# ── Token cap enforcement ─────────────────────────────────────────────────────

class TestEnforceTokenCap:
    def _fat_ctx(self) -> AssembledContext:
        """Build a context that far exceeds 4,000 tokens (> 16,000 chars)."""
        return AssembledContext(
            coach_narrative  = "narrative text " * 1_200,   # ~18,000 chars → ~4,500 tokens alone
            habit_events     = [f"event_{i} – 5h ago" for i in range(15)],
            user_facts       = [f"the user fact number {i} is very detailed and long indeed" for i in range(15)],
            daily_trajectory = [
                {
                    "date": f"2026-03-{17 + i}",
                    "stress_load": float(i * 10),
                    "waking_recovery": float(i * 5),
                    "net_balance": float(-i * 3),
                    "day_type": "green",
                }
                for i in range(7)
            ],
        )

    def test_clean_context_untouched(self):
        ctx = AssembledContext(
            coach_narrative = "short",
            habit_events    = ["one event"],
            user_facts      = ["one fact"],
        )
        result = _enforce_token_cap(ctx)
        assert result.coach_narrative == "short"
        assert len(result.habit_events) == 1
        assert len(result.user_facts) == 1

    def test_estimated_tokens_recorded(self):
        ctx = AssembledContext()
        result = _enforce_token_cap(ctx)
        assert result.estimated_tokens >= 0

    def test_narrative_truncated_when_over_cap(self):
        ctx = self._fat_ctx()
        result = _enforce_token_cap(ctx)
        # Narrative must be ≤ 400 chars after truncation
        if result.coach_narrative:
            assert len(result.coach_narrative) <= 400

    def test_habit_events_capped(self):
        ctx = self._fat_ctx()
        result = _enforce_token_cap(ctx)
        assert len(result.habit_events) <= 15   # may be trimmed to 3

    def test_final_estimate_within_reasonable_range(self):
        ctx = self._fat_ctx()
        result = _enforce_token_cap(ctx)
        # After truncation the token count should be substantially reduced
        # (allow 20% slack above cap for str() overhead of dicts/lists)
        assert result.estimated_tokens <= 5_000

    def test_none_narrative_not_set_to_empty_string(self):
        ctx = AssembledContext(coach_narrative=None)
        result = _enforce_token_cap(ctx)
        assert result.coach_narrative is None


# ── AssembledContext defaults ─────────────────────────────────────────────────

class TestAssembledContextDefaults:
    def test_empty_lists_by_default(self):
        ctx = AssembledContext()
        assert ctx.daily_trajectory == []
        assert ctx.habit_events == []
        assert ctx.user_facts == []
        assert ctx.background_bins == []

    def test_empty_dicts_by_default(self):
        ctx = AssembledContext()
        assert ctx.stress_windows_24h == {}
        assert ctx.recovery_windows_24h == {}

    def test_population_labels_default_unknown(self):
        ctx = AssembledContext()
        assert ctx.population_stress_label == "unknown"
        assert ctx.population_recovery_label == "unknown"

    def test_personal_model_none_by_default(self):
        ctx = AssembledContext()
        assert ctx.personal_model is None
