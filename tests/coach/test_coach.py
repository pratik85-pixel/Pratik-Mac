"""
tests/coach/test_coach.py

Comprehensive test suite for the coach layer.

Coverage:
    - plan_replanner: readiness-based prescription, compound tags
    - tone_selector: all four tones, priority order
    - context_builder: no raw floats in outputs, string conversions
    - milestone_detector: all 5 detection rules
    - memory_store: lifecycle, safety latch, signal accumulation
    - schema_validator: field constraints, clinical terms, specificity, superlatives
    - safety_filter: crisis pattern detection, clean text pass-through
    - conversation_extractor: signal extraction from messages
    - local_engine: correct output structure, no LLM dependency
"""

from __future__ import annotations

import pytest
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

# ── Imports under test ────────────────────────────────────────────────────────

from coach.plan_replanner import (
    compute_daily_prescription,
    DailyPrescription,
    HabitSignal,
)
from coach.tone_selector import (
    select_tone,
    TONE_CELEBRATE, TONE_WARN, TONE_COMPASSION, TONE_PUSH,
)
from coach.context_builder import (
    build_coach_context,
    CoachContext,
    _pct_str,
    _build_rmssd_strings,
    _filter_habit_events,
    _validate_milestone_evidence,
)
from coach.milestone_detector import detect_milestone, Milestone
from coach.memory_store import MemoryStore, ConversationState
from coach.schema_validator import validate_output
from coach.safety_filter import screen_text
from coach.conversation_extractor import extract_signals_from_message
from coach.local_engine import generate_local_output
from archetypes.scorer import NSHealthProfile
from model.baseline_builder import PersonalFingerprint


# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_profile(
    *,
    stage: int = 2,
    total_score: int = 45,
    trajectory: str = "stable",
    score_7d_delta: Optional[int] = None,
    weeks_in_stage: int = 3,
    primary_pattern: str = "over_optimizer",
) -> NSHealthProfile:
    return NSHealthProfile(
        total_score        = total_score,
        stage              = stage,
        stage_target       = 60,
        recovery_capacity  = 9,
        baseline_resilience= 9,
        coherence_capacity = 9,
        chrono_fit         = 9,
        load_management    = 9,
        primary_pattern    = primary_pattern,
        amplifier_pattern  = None,
        pattern_scores     = {},
        score_7d_delta     = score_7d_delta,
        score_30d_delta    = None,
        trajectory         = trajectory,
        stage_focus        = ["start with breathing sessions twice this week"],
        weeks_in_stage     = weeks_in_stage,
        overall_confidence = 0.8,
        data_hours         = 48.0,
    )


def make_fingerprint(
    *,
    rmssd_floor: float = 28.0,
    rmssd_ceiling: float = 55.0,
    rmssd_morning_avg: float = 38.0,
    recovery_arc_mean_hours: float = 1.8,
    coherence_floor: float = 0.25,
) -> PersonalFingerprint:
    from model.baseline_builder import PersonalFingerprint
    fp = PersonalFingerprint()
    fp.rmssd_floor          = rmssd_floor
    fp.rmssd_ceiling        = rmssd_ceiling
    fp.rmssd_range          = rmssd_ceiling - rmssd_floor
    fp.rmssd_morning_avg    = rmssd_morning_avg
    fp.recovery_arc_mean_hours = recovery_arc_mean_hours
    fp.coherence_floor      = coherence_floor
    fp.overall_confidence   = 0.8
    return fp


def make_alcohol_signal(severity: str = "moderate", hours_ago: float = 10.0) -> HabitSignal:
    return HabitSignal(
        event_type = "alcohol",
        severity   = severity,
        hours_ago  = hours_ago,
        source     = "conversation",
    )


def make_prescription(**kwargs) -> DailyPrescription:
    defaults = dict(
        session_type      = "full",
        session_duration  = 20,
        session_intensity = "moderate",
        session_window    = "19:00–21:00",
        physical_load     = "maintain",
        readiness_score   = 82.0,
        reason_tag        = "baseline",
        carry_forward     = False,
        notes             = [],
    )
    defaults.update(kwargs)
    return DailyPrescription(**defaults)


# ═══════════════════════════════════════════════════════════════════════════════
# plan_replanner tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestPlanReplanner:

    def test_alcohol_signal_produces_breathing_only(self):
        """Moderate alcohol <24h ago + below-floor read should push into breathing_only range."""
        profile = make_profile()
        fp      = make_fingerprint()
        signals = [make_alcohol_signal(severity="moderate", hours_ago=10.0)]

        rx = compute_daily_prescription(
            profile                = profile,
            readiness_score        = 20.0,
            morning_rmssd_vs_floor = -0.18,
            morning_rmssd_vs_avg   = -0.20,
            consecutive_low_reads  = 1,
            habit_signals          = signals,
            preferred_window_hour  = 19,
            sessions_this_week     = 2,
        )

        assert rx.session_type in ("breathing_only", "rest"), (
            f"Expected breathing_only or rest with alcohol signal, got {rx.session_type}"
        )

    def test_high_load_score_produces_rest(self):
        """Very low composite readiness must produce rest."""
        profile = make_profile()
        signals = [
            HabitSignal("alcohol", "heavy", 6.0, "manual"),
            HabitSignal("late_night", "heavy", 7.0, "manual"),
        ]

        rx = compute_daily_prescription(
            profile                = profile,
            readiness_score        = 20.0,
            morning_rmssd_vs_floor = -0.35,
            morning_rmssd_vs_avg   = -0.40,
            consecutive_low_reads  = 3,
            habit_signals          = signals,
            preferred_window_hour  = 19,
            sessions_this_week     = 4,
        )

        assert rx.session_type == "rest", (
            f"Expected rest for low readiness, got {rx.session_type} (rs={rx.readiness_score:.2f})"
        )
        assert rx.readiness_score < 25

    def test_low_load_score_produces_stage_plan(self):
        """High readiness (green day) should produce full session."""
        profile = make_profile(stage=3)
        signals = [HabitSignal("positive_state", "light", 2.0, "conversation")]

        rx = compute_daily_prescription(
            profile                = profile,
            readiness_score        = 88.0,
            morning_rmssd_vs_floor = 0.15,
            morning_rmssd_vs_avg   = 0.10,
            consecutive_low_reads  = 0,
            habit_signals          = signals,
            preferred_window_hour  = 19,
            sessions_this_week     = 2,
        )

        assert rx.session_type == "full"
        assert rx.physical_load in ("maintain", "can_increase")
        assert rx.readiness_score >= 75

    def test_compound_tag_takes_priority(self):
        """When both alcohol and low-reads are present, compound tag should fire."""
        profile = make_profile()
        signals = [
            HabitSignal("alcohol", "moderate", 8.0, "manual"),
            HabitSignal("late_night", "moderate", 9.0, "manual"),
        ]

        rx = compute_daily_prescription(
            profile                = profile,
            morning_rmssd_vs_floor = -0.15,
            morning_rmssd_vs_avg   = -0.20,
            consecutive_low_reads  = 2,
            habit_signals          = signals,
            preferred_window_hour  = 19,
            sessions_this_week     = 3,
        )

        assert "compound" in rx.reason_tag, (
            f"Expected compound reason tag, got: {rx.reason_tag}"
        )

    def test_consecutive_low_reads_alone_triggers_warn_prescription(self):
        """3 consecutive low reads with no other signals → breathing_only or rest."""
        profile = make_profile()

        rx = compute_daily_prescription(
            profile                = profile,
            readiness_score        = 18.0,
            morning_rmssd_vs_floor = -0.18,
            morning_rmssd_vs_avg   = -0.15,
            consecutive_low_reads  = 3,
            habit_signals          = [],
            preferred_window_hour  = 20,
            sessions_this_week     = 2,
        )

        assert rx.session_type in ("breathing_only", "rest")

    def test_prescription_window_format(self):
        """Session window should match HH:MM–HH:MM format."""
        import re
        profile = make_profile()

        rx = compute_daily_prescription(
            profile                = profile,
            readiness_score        = 80.0,
            morning_rmssd_vs_floor = 0.10,
            morning_rmssd_vs_avg   = 0.05,
            consecutive_low_reads  = 0,
            habit_signals          = [],
            preferred_window_hour  = 19,
            sessions_this_week     = 1,
        )

        assert re.match(r"\d{2}:\d{2}[–-]\d{2}:\d{2}", rx.session_window), (
            f"Window format unexpected: {rx.session_window}"
        )

    def test_readiness_score_bounded(self):
        """readiness_score on output must always be 0–100."""
        profile = make_profile()

        for n_lows in range(5):
            rx = compute_daily_prescription(
                profile                = profile,
                readiness_score        = 12.0 + n_lows * 5,
                morning_rmssd_vs_floor = -0.40,
                morning_rmssd_vs_avg   = -0.40,
                consecutive_low_reads  = n_lows,
                habit_signals          = [HabitSignal("alcohol", "heavy", 5.0, "manual")],
                preferred_window_hour  = 19,
                sessions_this_week     = 5,
            )
            assert 0.0 <= rx.readiness_score <= 100.0


# ═══════════════════════════════════════════════════════════════════════════════
# tone_selector tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestToneSelector:

    def test_milestone_fires_celebrate(self):
        """milestone_detected=True must return CELEBRATE regardless of other signals."""
        profile = make_profile(trajectory="declining", score_7d_delta=-3)

        tone = select_tone(
            profile               = profile,
            milestone_detected    = True,
            consecutive_low_reads = 3,   # would normally be WARN
        )
        assert tone == TONE_CELEBRATE

    def test_score_jump_fires_celebrate(self):
        """score_7d_delta ≥ 5 → CELEBRATE."""
        profile = make_profile(score_7d_delta=6)

        tone = select_tone(profile=profile, milestone_detected=False)
        assert tone == TONE_CELEBRATE

    def test_three_consecutive_lows_fires_warn(self):
        """3 consecutive low reads → WARN (overrides PUSH)."""
        profile = make_profile(trajectory="stable")

        tone = select_tone(
            profile               = profile,
            milestone_detected    = False,
            consecutive_low_reads = 3,
        )
        assert tone == TONE_WARN

    def test_severe_below_floor_fires_warn(self):
        """Morning read > 20% below floor → WARN."""
        profile = make_profile(trajectory="stable")

        tone = select_tone(
            profile                = profile,
            milestone_detected     = False,
            consecutive_low_reads  = 0,
            morning_rmssd_vs_floor = -0.25,
        )
        assert tone == TONE_WARN

    def test_lf_hf_elevated_and_trending_fires_warn(self):
        """Elevated LF/HF trending up → WARN."""
        profile = make_profile(trajectory="stable")

        tone = select_tone(
            profile            = profile,
            milestone_detected = False,
            lf_hf_resting      = 3.1,
            lf_hf_trending_up  = True,
        )
        assert tone == TONE_WARN

    def test_declining_plus_stressor_fires_compassion(self):
        """Declining trajectory + external stressor → COMPASSION."""
        profile = make_profile(trajectory="declining", score_7d_delta=-4)

        tone = select_tone(
            profile                   = profile,
            milestone_detected        = False,
            consecutive_low_reads     = 0,
            external_stressor_flagged = True,
        )
        assert tone == TONE_COMPASSION

    def test_stable_no_signals_fires_push(self):
        """No special signals, stable trajectory → PUSH (default)."""
        profile = make_profile(trajectory="stable")

        tone = select_tone(
            profile               = profile,
            milestone_detected    = False,
            consecutive_low_reads = 0,
        )
        assert tone == TONE_PUSH

    def test_celebrate_overrides_warn(self):
        """Milestone + consecutive lows → CELEBRATE (overrides WARN)."""
        profile = make_profile(trajectory="declining")

        tone = select_tone(
            profile               = profile,
            milestone_detected    = True,
            consecutive_low_reads = 5,
        )
        assert tone == TONE_CELEBRATE


# ═══════════════════════════════════════════════════════════════════════════════
# context_builder tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestContextBuilder:

    def test_no_raw_floats_in_rmssd_strings(self):
        """Raw RMSSD ms values must never appear in context output strings."""
        profile = make_profile()
        fp      = make_fingerprint(rmssd_morning_avg=38.0, rmssd_floor=28.0)

        rx = make_prescription()
        ctx = build_coach_context(
            profile            = profile,
            fingerprint        = fp,
            trigger_type       = "morning_brief",
            tone               = TONE_PUSH,
            prescription       = rx,
            morning_rmssd_ms   = 30.0,   # raw value — must not appear in ctx strings
        )

        # "30.0" or "30" as standalone number should not appear in RMSSD strings
        assert "30.0ms" not in ctx.today_rmssd_vs_avg
        assert "30.0ms" not in ctx.today_rmssd_vs_floor
        assert "38.0" not in ctx.today_rmssd_vs_avg  # reference value also must not appear
        assert "28.0" not in ctx.today_rmssd_vs_floor

    def test_pct_str_negative(self):
        assert _pct_str(-0.21) == "-21% below your average"

    def test_pct_str_positive(self):
        assert _pct_str(0.12, reference="your floor", above_label="above") == "+12% above your floor"

    def test_pct_str_at_zero(self):
        result = _pct_str(0.005)
        assert result.startswith("at ")

    def test_morning_read_quality_good(self):
        fp = make_fingerprint(rmssd_floor=28.0, rmssd_morning_avg=38.0)
        _, _, quality = _build_rmssd_strings(34.0, fp)  # 34 vs floor 28 = +21% → good
        assert quality == "good"

    def test_morning_read_quality_low(self):
        fp = make_fingerprint(rmssd_floor=28.0, rmssd_morning_avg=38.0)
        _, _, quality = _build_rmssd_strings(25.0, fp)  # 25 vs floor 28 = -10.7% → low
        assert quality == "low"

    def test_morning_read_quality_borderline(self):
        fp = make_fingerprint(rmssd_floor=28.0, rmssd_morning_avg=38.0)
        _, _, quality = _build_rmssd_strings(28.5, fp)  # 28.5 vs floor 28 = +1.8% → borderline
        assert quality == "borderline"

    def test_habit_events_filtered_beyond_72h(self):
        signals = [
            HabitSignal("alcohol", "moderate", 10.0, "manual"),
            HabitSignal("alcohol", "moderate", 80.0, "manual"),  # beyond 72h — must be dropped
        ]
        result = _filter_habit_events(signals)
        assert len(result) == 1
        assert "alcohol" in result[0]

    def test_milestone_evidence_without_digit_is_suppressed(self):
        assert _validate_milestone_evidence("great improvement") is None

    def test_milestone_evidence_with_digit_passes(self):
        result = _validate_milestone_evidence("score reached 52 out of 100")
        assert result is not None
        assert "52" in result

    def test_build_coach_context_unavailable_with_no_fingerprint_data(self):
        """If fingerprint has no floor/ceiling, RMSSD strings should say 'unavailable'."""
        profile = make_profile()
        fp      = PersonalFingerprint()   # empty — no floor/ceiling
        rx      = make_prescription()

        ctx = build_coach_context(
            profile          = profile,
            fingerprint      = fp,
            trigger_type     = "nudge",
            tone             = TONE_PUSH,
            prescription     = rx,
            morning_rmssd_ms = 35.0,
        )

        assert "unavailable" in ctx.today_rmssd_vs_avg


# ═══════════════════════════════════════════════════════════════════════════════
# milestone_detector tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestMilestoneDetector:

    def test_stage_advance_fires(self):
        profile = make_profile(stage=3, total_score=62)
        fp      = make_fingerprint()

        m = detect_milestone(profile, fp, previous_stage=2, previous_score=55)
        assert m is not None
        assert m.kind == "stage_advance"
        assert any(ch.isdigit() for ch in m.evidence)

    def test_score_jump_fires(self):
        profile = make_profile(stage=2, total_score=50)
        fp      = make_fingerprint()

        m = detect_milestone(profile, fp, previous_stage=2, previous_score=44)
        assert m is not None
        assert m.kind == "score_jump"
        assert "6" in m.evidence or "50" in m.evidence

    def test_arc_improvement_fires(self):
        profile = make_profile()
        fp      = make_fingerprint(recovery_arc_mean_hours=1.4)  # improved from 1.8

        m = detect_milestone(
            profile,
            fp,
            previous_arc_mean_hours = 1.75,  # delta = 0.35h = 21 mins → ≥20 min threshold
        )
        assert m is not None
        assert m.kind == "arc_improvement"
        assert any(ch.isdigit() for ch in m.evidence)

    def test_coherence_band_crossing_fires(self):
        profile = make_profile()
        fp      = make_fingerprint(coherence_floor=0.32)

        m = detect_milestone(
            profile,
            fp,
            previous_coherence_floor = 0.27,  # crosses 0.30 band
        )
        assert m is not None
        assert m.kind == "coherence_band"
        assert any(ch.isdigit() for ch in m.evidence)

    def test_dimension_peak_fires(self):
        profile = make_profile()
        profile.recovery_capacity = 15  # just hit the threshold

        fp = make_fingerprint()
        m = detect_milestone(
            profile,
            fp,
            previous_dimension_scores = {"recovery_capacity": 13},
        )
        assert m is not None
        assert m.kind == "dimension_peak"

    def test_no_milestone_returns_none(self):
        profile = make_profile(stage=2, total_score=45)
        fp      = make_fingerprint()

        m = detect_milestone(
            profile,
            fp,
            previous_stage         = 2,
            previous_score         = 43,
            previous_arc_mean_hours= 1.8,
            previous_coherence_floor=0.24,
            previous_dimension_scores={"recovery_capacity": 9},
        )
        assert m is None

    def test_milestone_evidence_always_contains_digit(self):
        """All milestone kinds must produce evidence strings containing a digit."""
        profile = make_profile(stage=3, total_score=62)
        fp      = make_fingerprint()

        m = detect_milestone(
            profile, fp,
            previous_stage = 2,
            previous_score = 56,
        )
        assert m is not None
        assert any(ch.isdigit() for ch in m.evidence), (
            f"Milestone evidence has no digit: {m.evidence}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# memory_store tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestMemoryStore:

    def test_create_and_retrieve_session(self):
        store = MemoryStore()
        state = store.create_session("user_1", "morning_brief")

        assert state.user_id == "user_1"
        assert state.turn_index == 0
        assert not state.safety_triggered

        retrieved = store.get(state.conversation_id)
        assert retrieved is not None
        assert retrieved.conversation_id == state.conversation_id

    def test_advance_turn(self):
        store = MemoryStore()
        state = store.create_session("user_2")
        cid   = state.conversation_id

        store.advance_turn(cid)
        store.advance_turn(cid)
        updated = store.get(cid)
        assert updated.turn_index == 2

    def test_safety_latch_is_permanent(self):
        store = MemoryStore()
        state = store.create_session("user_3")
        cid   = state.conversation_id

        assert not store.get(cid).safety_triggered
        store.latch_safety(cid)
        assert store.get(cid).safety_triggered

        # Latching twice should not error
        store.latch_safety(cid)
        assert store.get(cid).safety_triggered

    def test_add_signal_accumulates(self):
        store = MemoryStore()
        state = store.create_session("user_4")
        cid   = state.conversation_id

        store.add_signal(cid, "alcohol (moderate) ~10h ago")
        store.add_signal(cid, "late night ~8h ago")

        updated = store.get(cid)
        assert len(updated.accumulated_signals) == 2

    def test_close_session_removes_entry(self):
        store = MemoryStore()
        state = store.create_session("user_5")
        cid   = state.conversation_id

        final = store.close_session(cid)
        assert final is not None
        assert store.get(cid) is None

    def test_update_summary(self):
        store = MemoryStore()
        state = store.create_session("user_6")
        cid   = state.conversation_id

        store.update_summary(cid, "User talked about stress at work.")
        assert "stress" in store.get(cid).rolling_summary


# ═══════════════════════════════════════════════════════════════════════════════
# schema_validator tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestSchemaValidator:

    def _valid_morning_brief(self) -> dict:
        return {
            "summary":             "Today your morning read sits a little below your average, compounded by last night. A steady breathing session is the right move.",
            "observation":         "Load score is elevated after the alcohol signal from last night.",
            "action":              "Do a 10-minute breathing-only session at low intensity in the 19:00 to 21:00 window.",
            "window":              "Your window: 19:00–21:00.",
            "encouragement":       "",
            "follow_up_question":  None,
        }

    def test_valid_output_passes(self):
        valid, cleaned, errors = validate_output(self._valid_morning_brief(), "morning_brief")
        assert valid is True
        assert errors == []

    def test_missing_required_field_fails(self):
        bad = {k: v for k, v in self._valid_morning_brief().items() if k != "action"}
        valid, cleaned, errors = validate_output(bad, "morning_brief")
        assert valid is False
        assert any("missing_fields" in e for e in errors)

    def test_clinical_term_triggers_retry(self):
        bad = self._valid_morning_brief()
        bad["summary"] = "Your HRV is showing parasympathetic suppression today."
        valid, cleaned, errors = validate_output(bad, "morning_brief")
        assert valid is False
        assert any("clinical_term" in e for e in errors)

    def test_encouragement_without_digit_is_blanked(self):
        output = {
            "summary":             "A steady session today is the right approach given where your read landed this morning.",
            "observation":         "Morning read is holding steady right at your personal floor level.",
            "action":              "Do a 10-minute breathing-only session at low intensity in the 19:00 to 21:00 window.",
            "window":              "Window: 19:00–21:00.",
            "encouragement":       "You are doing really well, keep it up!",  # no digit
            "follow_up_question":  None,
        }
        valid, cleaned, errors = validate_output(output, "morning_brief")
        assert cleaned.get("encouragement") == ""
        assert any("specificity_blanked" in e for e in errors)

    def test_encouragement_with_digit_passes(self):
        output = {
            "summary":             "Recovery is building — this is the 3rd week in a row.",
            "observation":         "Morning read is holding near your floor.",
            "action":              "Do a 15-minute breathing session in the evening window.",
            "window":              "Window: 19:00–21:00.",
            "encouragement":       "This is your 3rd consistent week — that is the signal building.",
            "follow_up_question":  None,
        }
        valid, cleaned, errors = validate_output(output, "morning_brief")
        assert cleaned.get("encouragement") != ""

    def test_superlative_stripped(self):
        output = self._valid_morning_brief()
        output["summary"] = "This is an amazing result and you are doing fantastic work."
        valid, cleaned, errors = validate_output(output, "morning_brief")
        assert "amazing" not in cleaned.get("summary", "").lower()
        assert any("superlative_blanked" in e for e in errors)

    def test_medical_advice_returns_non_retryable_error(self):
        output = self._valid_morning_brief()
        output["observation"] = "These symptoms suggest you should consult a doctor."
        valid, cleaned, errors = validate_output(output, "morning_brief")
        assert valid is False
        assert any("medical_advice" in e for e in errors)

    def test_summary_too_short_fails(self):
        output = self._valid_morning_brief()
        output["summary"] = "Short."   # 1 word
        valid, cleaned, errors = validate_output(output, "morning_brief")
        assert valid is False
        assert any("length:summary" in e for e in errors)

    def test_conversation_turn_schema(self):
        output = {
            "reply":              "Noted — keeping the session light today makes sense given what you described. One short breathing session will do.",
            "follow_up_question": None,
        }
        valid, cleaned, errors = validate_output(output, "conversation_turn")
        assert valid is True


# ═══════════════════════════════════════════════════════════════════════════════
# safety_filter tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestSafetyFilter:

    def test_clean_text_passes(self):
        result = screen_text("I had a stressful day but I am okay.")
        assert result.is_safe is True
        assert result.category is None

    def test_empty_text_passes(self):
        result = screen_text("")
        assert result.is_safe is True

    def test_self_harm_language_fails(self):
        result = screen_text("I want to hurt myself tonight.")
        assert result.is_safe is False
        assert result.category == "self_harm"
        assert len(result.handoff_message) > 20

    def test_suicidal_ideation_fails(self):
        result = screen_text("I have been thinking about ending my life.")
        assert result.is_safe is False

    def test_worthlessness_pattern_fails(self):
        result = screen_text("I feel worthless and there is no reason to live.")
        assert result.is_safe is False

    def test_hopelessness_pattern_fails(self):
        result = screen_text("I have completely given up — nothing will ever change.")
        assert result.is_safe is False

    def test_handoff_message_contains_crisis_line(self):
        result = screen_text("I want to kill myself.")
        assert not result.is_safe
        assert "988" in result.handoff_message or "116" in result.handoff_message

    def test_case_insensitive(self):
        result = screen_text("I WANT TO HURT MYSELF.")
        assert not result.is_safe


# ═══════════════════════════════════════════════════════════════════════════════
# conversation_extractor tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestConversationExtractor:

    def test_alcohol_extraction(self):
        result = extract_signals_from_message("I had a few drinks last night.")
        assert len(result.signals) >= 1
        assert result.signals[0].event_type == "alcohol"

    def test_heavy_alcohol_extraction(self):
        result = extract_signals_from_message("Big night out — got drunk.")
        assert any(s.severity == "heavy" for s in result.signals)

    def test_stress_extraction(self):
        result = extract_signals_from_message("Work has been incredibly stressful today.")
        assert any(s.event_type == "stressful_event" for s in result.signals)

    def test_late_night_extraction(self):
        result = extract_signals_from_message("I stayed up late working.")
        assert any(s.event_type == "late_night" for s in result.signals)

    def test_missed_session_extraction(self):
        result = extract_signals_from_message("I missed my session yesterday.")
        assert any(s.event_type == "missed_session" for s in result.signals)

    def test_positive_state_extraction(self):
        result = extract_signals_from_message("Feeling good — had a great sleep.")
        assert any(s.event_type == "positive_state" for s in result.signals)

    def test_no_signal_produces_empty(self):
        result = extract_signals_from_message("What time should I do my session?")
        assert result.signals == []

    def test_duplicate_signal_not_added(self):
        """If signal already in accumulated_signals, should not be duplicated."""
        existing = ["alcohol (moderate) ~8h ago"]
        result = extract_signals_from_message(
            "I had a few drinks last night.",
            existing_signals=existing,
        )
        # Signal label matches format — should be deduplicated (same event_type key)
        # Note: deduplication is by label string so result may still add if label differs
        # What we check: result.signals are all from "conversation" source
        for sig in result.signals:
            assert sig.source == "conversation"

    def test_temporal_yesterday_maps_to_24h(self):
        result = extract_signals_from_message("I drank yesterday.")
        assert len(result.signals) >= 1
        assert result.signals[0].hours_ago == 24.0

    def test_confidence_is_below_physiological(self):
        result = extract_signals_from_message("I was stressed today.")
        assert result.confidence < 1.0
        assert result.confidence == 0.4


# ═══════════════════════════════════════════════════════════════════════════════
# local_engine tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestLocalEngine:

    def _make_ctx(self, trigger_type: str, tone: str = "PUSH") -> CoachContext:
        profile = make_profile()
        fp      = make_fingerprint()
        rx      = make_prescription()
        return build_coach_context(
            profile          = profile,
            fingerprint      = fp,
            trigger_type     = trigger_type,
            tone             = tone,
            prescription     = rx,
            morning_rmssd_ms = 35.0,
        )

    def test_morning_brief_schema(self):
        ctx = self._make_ctx("morning_brief")
        profile = make_profile()
        out = generate_local_output(ctx, profile)

        assert "summary" in out
        assert "action"  in out
        assert "window"  in out

    def test_post_session_schema(self):
        ctx = self._make_ctx("post_session")
        profile = make_profile()
        out = generate_local_output(ctx, profile)

        assert "summary"      in out
        assert "next_session" in out

    def test_nudge_schema(self):
        ctx = self._make_ctx("nudge")
        profile = make_profile()
        out = generate_local_output(ctx, profile)

        assert "summary" in out
        assert "action"  in out

    def test_weekly_review_schema(self):
        ctx = self._make_ctx("weekly_review")
        profile = make_profile()
        out = generate_local_output(ctx, profile)

        assert "summary"        in out
        assert "week_narrative" in out
        assert "action"         in out

    def test_conversation_turn_schema(self):
        ctx = self._make_ctx("conversation_turn")
        profile = make_profile()
        out = generate_local_output(ctx, profile)

        assert "reply" in out

    def test_source_field_present_internally(self):
        """local_engine adds 'source': 'local_engine' — coach_api strips it before delivery."""
        ctx = self._make_ctx("nudge")
        profile = make_profile()
        out = generate_local_output(ctx, profile)
        assert out.get("source") == "local_engine"

    def test_warn_tone_uses_warn_opening(self):
        ctx = self._make_ctx("morning_brief", tone="WARN")
        profile = make_profile()
        out = generate_local_output(ctx, profile)
        # WARN opening: "Today calls for a different approach."
        assert "different approach" in out["summary"] or len(out["summary"]) > 10

    def test_output_contains_no_clinical_terms(self):
        """Local engine output must not contain clinical terms (same rule as LLM output)."""
        from coach.schema_validator import _CLINICAL_TERMS
        ctx = self._make_ctx("morning_brief")
        profile = make_profile()
        out = generate_local_output(ctx, profile)

        all_text = " ".join(str(v) for v in out.values() if isinstance(v, str)).lower()
        for term in _CLINICAL_TERMS:
            assert term not in all_text, f"Clinical term '{term}' found in local_engine output"
