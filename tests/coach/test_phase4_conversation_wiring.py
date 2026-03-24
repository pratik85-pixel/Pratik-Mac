"""
tests/coach/test_phase4_conversation_wiring.py

Unit tests for Phase 4: DataAssembler wiring into live conversation turns.

Covers:
  - _build_physio_section() helper (new)
  - avoid_items field propagation through CoachContext / build_coach_context()
  - _build_conversation_turn() prompt content: TODAY'S PHYSIO present / absent
  - Graceful degradation: empty prompt block when no assembled data
"""

from __future__ import annotations

import pytest
from typing import Optional

from archetypes.scorer import NSHealthProfile
from coach.context_builder import CoachContext, build_coach_context
from coach.plan_replanner import DailyPrescription
from coach.prompt_templates import _build_physio_section, _build_conversation_turn
from coach.tone_selector import TONE_DESCRIPTIONS
from model.baseline_builder import PersonalFingerprint


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _make_profile(trajectory: str = "stable") -> NSHealthProfile:
    return NSHealthProfile(
        total_score=45,
        stage=2,
        stage_target=60,
        recovery_capacity=9,
        baseline_resilience=9,
        coherence_capacity=9,
        chrono_fit=9,
        load_management=9,
        primary_pattern="over_optimizer",
        amplifier_pattern=None,
        pattern_scores={},
        score_7d_delta=None,
        score_30d_delta=None,
        trajectory=trajectory,
        stage_focus=["breathe"],
        weeks_in_stage=2,
        overall_confidence=0.8,
        data_hours=48.0,
    )


def _make_prescription() -> DailyPrescription:
    return DailyPrescription(
        session_type="breathing_only",
        session_duration=10,
        session_intensity="low",
        session_window="19:00–21:00",
        physical_load="hold",
        reason_tag="stable",
        load_score=0.5,
    )


def _make_fingerprint() -> PersonalFingerprint:
    fp = PersonalFingerprint()
    fp.rmssd_floor          = 28.0
    fp.rmssd_ceiling        = 55.0
    fp.rmssd_range          = 27.0
    fp.rmssd_morning_avg    = 38.0
    fp.recovery_arc_mean_hours = 1.8
    fp.coherence_floor      = 0.25
    fp.overall_confidence   = 0.8
    return fp


def _make_ctx(
    *,
    stress_score: Optional[int] = None,
    recovery_score: Optional[int] = None,
    net_balance: Optional[float] = None,
    avoid_items: Optional[list[dict]] = None,
    trajectory: str = "stable",
) -> CoachContext:
    profile = _make_profile(trajectory=trajectory)
    fp = _make_fingerprint()
    rx = _make_prescription()
    return build_coach_context(
        profile=profile,
        fingerprint=fp,
        trigger_type="conversation_turn",
        tone="PUSH",
        prescription=rx,
        last_user_said="How am I doing today?",
        net_balance=net_balance,
        stress_score=stress_score,
        recovery_score=recovery_score,
        avoid_items=avoid_items,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: _build_physio_section()
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildPhysioSection:

    def test_empty_when_no_scores(self):
        ctx = _make_ctx()   # all None
        assert _build_physio_section(ctx) == ""

    def test_section_header_present_when_stress_score_set(self):
        ctx = _make_ctx(stress_score=62)
        section = _build_physio_section(ctx)
        assert "TODAY'S PHYSIO" in section

    def test_section_header_present_when_recovery_score_set(self):
        ctx = _make_ctx(recovery_score=74)
        section = _build_physio_section(ctx)
        assert "TODAY'S PHYSIO" in section

    def test_section_header_present_when_net_balance_set(self):
        ctx = _make_ctx(net_balance=3.5)
        section = _build_physio_section(ctx)
        assert "TODAY'S PHYSIO" in section

    def test_stress_score_formatted_as_per_100(self):
        ctx = _make_ctx(stress_score=55)
        section = _build_physio_section(ctx)
        assert "55/100" in section
        assert "stress load" in section

    def test_recovery_score_formatted_as_per_100(self):
        ctx = _make_ctx(recovery_score=80)
        section = _build_physio_section(ctx)
        assert "80/100" in section
        assert "recovery" in section

    def test_positive_net_balance_shows_plus_sign(self):
        ctx = _make_ctx(net_balance=4.2)
        section = _build_physio_section(ctx)
        assert "+4.2" in section

    def test_negative_net_balance_shows_minus_sign(self):
        ctx = _make_ctx(net_balance=-3.1)
        section = _build_physio_section(ctx)
        assert "-3.1" in section

    def test_zero_net_balance_shows_plus_sign(self):
        ctx = _make_ctx(net_balance=0.0)
        section = _build_physio_section(ctx)
        assert "+0.0" in section

    def test_trajectory_present_when_non_empty(self):
        ctx = _make_ctx(stress_score=50, trajectory="improving")
        section = _build_physio_section(ctx)
        assert "7-day direction" in section
        assert "improving" in section

    def test_trajectory_absent_when_unknown(self):
        ctx = _make_ctx(stress_score=50, trajectory="unknown")
        section = _build_physio_section(ctx)
        assert "7-day direction" not in section

    def test_avoid_items_shown_when_present(self):
        items = [{"slug_or_label": "hard_session", "reason": "residual fatigue signal from last 48h"}]
        ctx = _make_ctx(stress_score=60, avoid_items=items)
        section = _build_physio_section(ctx)
        assert "Avoid today" in section
        assert "residual fatigue" in section

    def test_avoid_items_uses_reason_over_slug(self):
        items = [{"slug_or_label": "slug_xyz", "reason": "elevated stress windows today"}]
        ctx = _make_ctx(stress_score=60, avoid_items=items)
        section = _build_physio_section(ctx)
        assert "elevated stress windows today" in section
        assert "slug_xyz" not in section

    def test_avoid_items_falls_back_to_slug_when_no_reason(self):
        items = [{"slug_or_label": "hard_session", "reason": ""}]
        ctx = _make_ctx(stress_score=60, avoid_items=items)
        section = _build_physio_section(ctx)
        assert "hard_session" in section

    def test_avoid_items_capped_at_two(self):
        items = [
            {"slug_or_label": "a", "reason": "reason A"},
            {"slug_or_label": "b", "reason": "reason B"},
            {"slug_or_label": "c", "reason": "reason C"},  # should be dropped
        ]
        ctx = _make_ctx(stress_score=60, avoid_items=items)
        section = _build_physio_section(ctx)
        assert "reason A" in section
        assert "reason B" in section
        assert "reason C" not in section

    def test_avoid_items_absent_when_list_empty(self):
        ctx = _make_ctx(stress_score=60, avoid_items=[])
        section = _build_physio_section(ctx)
        assert "Avoid today" not in section

    def test_all_three_scores_present(self):
        ctx = _make_ctx(stress_score=70, recovery_score=55, net_balance=-1.8)
        section = _build_physio_section(ctx)
        assert "70/100" in section
        assert "55/100" in section
        assert "-1.8" in section

    def test_section_ends_with_newline(self):
        ctx = _make_ctx(stress_score=50)
        section = _build_physio_section(ctx)
        assert section.endswith("\n")


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: avoid_items propagation through CoachContext
# ═══════════════════════════════════════════════════════════════════════════════

class TestAvoidItemsPropagation:

    def test_avoid_items_default_empty_list(self):
        ctx = _make_ctx()
        assert ctx.avoid_items == []

    def test_avoid_items_passed_through_build_coach_context(self):
        items = [{"slug_or_label": "intense_session", "reason": "3 consecutive high-stress days"}]
        ctx = _make_ctx(avoid_items=items)
        assert len(ctx.avoid_items) == 1
        assert ctx.avoid_items[0]["reason"] == "3 consecutive high-stress days"

    def test_multiple_avoid_items_preserved(self):
        items = [
            {"slug_or_label": "a", "reason": "reason A"},
            {"slug_or_label": "b", "reason": "reason B"},
        ]
        ctx = _make_ctx(avoid_items=items)
        assert len(ctx.avoid_items) == 2

    def test_none_avoid_items_becomes_empty_list(self):
        """build_coach_context(avoid_items=None) must produce ctx.avoid_items == []."""
        profile = _make_profile()
        fp = _make_fingerprint()
        rx = _make_prescription()
        ctx = build_coach_context(
            profile=profile,
            fingerprint=fp,
            trigger_type="conversation_turn",
            tone="PUSH",
            prescription=rx,
            avoid_items=None,
        )
        assert ctx.avoid_items == []


# ═══════════════════════════════════════════════════════════════════════════════
# Tests: _build_conversation_turn() prompt integration
# ═══════════════════════════════════════════════════════════════════════════════

class TestConversationTurnPrompt:

    def _prompt(self, **kwargs) -> str:
        ctx = _make_ctx(**kwargs)
        tone_desc = TONE_DESCRIPTIONS.get(ctx.tone, "")
        return _build_conversation_turn(ctx, tone_desc)

    def test_physio_block_absent_when_no_data(self):
        prompt = self._prompt()
        assert "TODAY'S PHYSIO" not in prompt

    def test_physio_block_present_when_stress_score_set(self):
        prompt = self._prompt(stress_score=68)
        assert "TODAY'S PHYSIO" in prompt

    def test_physio_block_present_when_recovery_score_set(self):
        prompt = self._prompt(recovery_score=45)
        assert "TODAY'S PHYSIO" in prompt

    def test_physio_block_present_when_net_balance_set(self):
        prompt = self._prompt(net_balance=2.1)
        assert "TODAY'S PHYSIO" in prompt

    def test_old_current_scores_label_absent(self):
        """CURRENT SCORES: label (old design) must not appear."""
        prompt = self._prompt(stress_score=60, recovery_score=75)
        assert "CURRENT SCORES:" not in prompt

    def test_prompt_still_contains_trigger_line(self):
        prompt = self._prompt(stress_score=60)
        assert "TRIGGER: conversation_turn" in prompt

    def test_prompt_still_contains_json_schema(self):
        prompt = self._prompt()
        assert '"reply"' in prompt
        assert '"follow_up_question"' in prompt

    def test_avoid_items_in_prompt_when_data_present(self):
        items = [{"slug_or_label": "intense_session", "reason": "recovery debt building"}]
        prompt = self._prompt(stress_score=70, avoid_items=items)
        assert "Avoid today" in prompt
        assert "recovery debt" in prompt

    def test_no_raw_metric_values_in_physio_block(self):
        """Scores must appear as /100 values only — no raw RMSSD, ms, or % vs baseline."""
        ctx = _make_ctx(stress_score=72, recovery_score=61, net_balance=1.5)
        tone_desc = TONE_DESCRIPTIONS.get(ctx.tone, "")
        prompt = _build_conversation_turn(ctx, tone_desc)
        assert "ms" not in prompt.split("TODAY'S PHYSIO")[1].split("\n\n")[0]
        assert "rmssd" not in prompt.lower().split("today's physio")[1].split("\n\n")[0]

    def test_physio_block_omitted_gracefully_on_empty_scores(self):
        """Prompt must be valid and complete even when no physio data is available."""
        prompt = self._prompt()
        assert "TRIGGER" in prompt
        assert "USER JUST SAID" in prompt
        assert "Output this JSON" in prompt
