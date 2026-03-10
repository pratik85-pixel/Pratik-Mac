"""
coach/local_engine.py

Offline fallback coaching engine — no LLM required.

Design
------
Produces structurally identical output to the LLM path.
Used when:
    - No network available
    - Two LLM retries have failed
    - User is in an "always offline session" (onboarding flag)

The local engine uses only:
    - profile.stage_focus[0]  — primary coaching focus for this stage
    - prescription.reason_tag — contextual explanation for today's directive
    - prescription.*          — session parameters
    - ctx.tone                — pre-selected tone

Output quality: deterministic, correct, slightly formulaic.
Never indicates to the user that they are seeing a fallback.
Adds internal metadata field: "source": "local_engine" (stripped before user delivery).
"""

from __future__ import annotations

from typing import Optional

from archetypes.scorer import NSHealthProfile
from coach.context_builder import CoachContext
from coach.plan_replanner import DailyPrescription


# ── Stage focus fallback map ───────────────────────────────────────────────────
# Used when stage_focus list is empty (shouldn't happen but guarded)

_STAGE_FOCUS_FALLBACK: dict[int, str] = {
    0: "start with a single short breathing session this week",
    1: "keep the daily check-ins consistent and aim for two sessions",
    2: "build session regularity — three times this week if body allows",
    3: "focus on sustaining the habit and letting recovery compound",
    4: "maintain the pattern and notice the timing that works best for you",
    5: "challenge the system slightly — extend one session beyond your normal duration",
}

# ── Tone openings ──────────────────────────────────────────────────────────────

_TONE_OPENINGS: dict[str, str] = {
    "CELEBRATE": "Something worth noting — the data is moving.",
    "WARN":      "Today calls for a different approach.",
    "COMPASSION":"The body is telling you something — worth listening to today.",
    "PUSH":      "Conditions look good. Time to make use of that.",
}

_TONE_CLOSINGS: dict[str, str] = {
    "CELEBRATE": "Keep going.",
    "WARN":      "One step at a time.",
    "COMPASSION":"Softer is better today — that's the work.",
    "PUSH":      "Do the session.",
}

# ── Reason tag descriptions ───────────────────────────────────────────────────

_REASON_DESCRIPTIONS: dict[str, str] = {
    "alcohol_recovery":           "Your body is still clearing last night.",
    "alcohol_recovery_compound":  "A combination of alcohol and accumulated load is showing up.",
    "sustained_depletion":        "Several low reads in a row — the system needs a lighter day.",
    "reported_stress":            "An external stressor is adding to the baseline load.",
    "late_night_compound":        "Late night combined with other signals — keep it gentle.",
    "chronic_load_compound":      "The cumulative load this week needs to be respected.",
    "alcohol_late_night_compound":"Alcohol and late night together — rest is the best training today.",
    "weekly_load":                "The week's load is accumulating — a lighter day today helps the week.",
    "low_morning_read":           "This morning's read is lower than your usual — adapt accordingly.",
    "positive_state":             "Everything is pointing in the right direction today.",
    "stage_progression":          "Your stage suggests a progressive challenge is appropriate.",
    "baseline":                   "Conditions are standard — stick to the plan.",
}


# ── Public API ────────────────────────────────────────────────────────────────

def generate_local_output(
    ctx: CoachContext,
    profile: NSHealthProfile,
) -> dict:
    """
    Generate coaching output without an LLM.

    Parameters
    ----------
    ctx : CoachContext
        Fully assembled context.
    profile : NSHealthProfile
        Current scoring profile. Used for stage_focus text.

    Returns
    -------
    dict
        JSON-compatible dict matching the output schema for ctx.trigger_type.
        Includes "source": "local_engine" (stripped by coach_api before delivery).
    """
    tone    = ctx.tone
    rx      = ctx.prescription
    opening = _TONE_OPENINGS.get(tone, "Here's your check-in for today.")
    closing = _TONE_CLOSINGS.get(tone, "")
    reason  = _REASON_DESCRIPTIONS.get(rx.reason_tag, "Today's conditions are noted.")
    focus   = _get_stage_focus(profile)

    builder = _LOCAL_BUILDERS.get(ctx.trigger_type, _build_fallback_generic)
    output  = builder(ctx, rx, tone, opening, closing, reason, focus)
    output["source"] = "local_engine"
    return output


# ── Trigger-specific local builders ──────────────────────────────────────────

def _build_local_morning_brief(
    ctx: CoachContext,
    rx: DailyPrescription,
    tone: str,
    opening: str,
    closing: str,
    reason: str,
    focus: str,
) -> dict:
    session_str = f"{rx.session_duration}-minute {rx.session_type.replace('_', ' ')}"
    return {
        "summary": (
            f"{opening} {reason} "
            f"Today: {session_str} in the {rx.session_window} window."
        ),
        "observation": f"Load score today is {rx.load_score:.2f} — {rx.reason_tag.replace('_', ' ')}.",
        "action": (
            f"Do a {session_str} at {rx.session_intensity} intensity "
            f"in the {rx.session_window} window."
        ),
        "window": f"Your window today: {rx.session_window}.",
        "encouragement": "",
        "follow_up_question": None,
    }


def _build_local_post_session(
    ctx: CoachContext,
    rx: DailyPrescription,
    tone: str,
    opening: str,
    closing: str,
    reason: str,
    focus: str,
) -> dict:
    return {
        "summary": f"Session logged. {focus}",
        "observation": "The session data has been recorded for your baseline.",
        "reinforcement": "",
        "next_session": (
            f"Next: {rx.session_type.replace('_', ' ')} session "
            f"in the {rx.session_window} window."
        ),
        "follow_up_question": None,
    }


def _build_local_nudge(
    ctx: CoachContext,
    rx: DailyPrescription,
    tone: str,
    opening: str,
    closing: str,
    reason: str,
    focus: str,
) -> dict:
    session_str = f"{rx.session_duration}-minute {rx.session_type.replace('_', ' ')}"
    return {
        "summary": f"{opening} {reason}",
        "action": f"Do a {session_str} in the {rx.session_window} window. {closing}",
        "follow_up_question": None,
    }


def _build_local_weekly_review(
    ctx: CoachContext,
    rx: DailyPrescription,
    tone: str,
    opening: str,
    closing: str,
    reason: str,
    focus: str,
) -> dict:
    delta_str = (
        f"Score moved {ctx.score_7d_delta:+d} points this week."
        if ctx.score_7d_delta is not None
        else "Score data is being collected."
    )
    return {
        "summary": f"{opening} {delta_str}",
        "week_narrative": (
            f"Trajectory this week: {ctx.trajectory}. "
            f"{ctx.load_trend}. "
            f"{ctx.recovery_pattern_note}. "
            f"Sessions completed: {ctx.sessions_this_week}."
        ),
        "dimension_spotlight": "Dimension data is available in your profile.",
        "encouragement": "",
        "action": f"Coming week: {focus}",
        "follow_up_question": None,
    }


def _build_local_conversation_turn(
    ctx: CoachContext,
    rx: DailyPrescription,
    tone: str,
    opening: str,
    closing: str,
    reason: str,
    focus: str,
) -> dict:
    return {
        "reply": (
            f"Got it. {reason} "
            f"Today's plan stays: {rx.session_duration}-minute "
            f"{rx.session_type.replace('_', ' ')} in the {rx.session_window} window. "
            f"{closing}"
        ),
        "plan_delta": None,
        "follow_up_question": None,
    }


def _build_fallback_generic(
    ctx: CoachContext,
    rx: DailyPrescription,
    tone: str,
    opening: str,
    closing: str,
    reason: str,
    focus: str,
) -> dict:
    return {
        "summary": f"{opening} {reason}",
        "action": f"{rx.session_duration} minutes, {rx.session_type.replace('_',' ')}, {rx.session_window}.",
        "follow_up_question": None,
    }


_LOCAL_BUILDERS = {
    "morning_brief":     _build_local_morning_brief,
    "post_session":      _build_local_post_session,
    "nudge":             _build_local_nudge,
    "weekly_review":     _build_local_weekly_review,
    "conversation_turn": _build_local_conversation_turn,
}


# ── Helper ────────────────────────────────────────────────────────────────────

def _get_stage_focus(profile: NSHealthProfile) -> str:
    if profile.stage_focus:
        return profile.stage_focus[0]
    return _STAGE_FOCUS_FALLBACK.get(profile.stage, "continue the current pattern")
