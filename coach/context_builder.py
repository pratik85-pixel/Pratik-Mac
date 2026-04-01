"""
coach/context_builder.py

Assembles the CoachContext dataclass — the complete structured context
the LLM receives for every coaching message.

Design contract
---------------
NO raw metric values reach the LLM.
Every float is converted to a personal-relative string before inclusion.
The LLM receives only direction + magnitude in plain English.

Example conversions:
    34.1ms  →  "-21% vs your average"
    11.2ms  →  "12% above your floor"
    2.4hrs  →  "arcs completing in ~2.4hrs vs your 1.8hr average"

This file defines:
    CoachContext       — the full payload consumed by prompt_templates.py
    build_coach_context() — the public assembly function
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from archetypes.scorer import NSHealthProfile
from model.baseline_builder import PersonalFingerprint
from coach.plan_replanner import DailyPrescription, HabitSignal


# ── Pattern labels + summaries ────────────────────────────────────────────────

_PATTERN_LABELS: dict[str, str] = {
    "over_optimizer":      "The Over-Optimiser",
    "sympathetic_dominant": "The Sympathetic Dominant",
    "under_activator":     "The Under-Activator",
    "sleep_compromised":   "The Sleep-Compromised",
    "resilient_floor":     "The Resilient Floor",
    "early_responder":     "The Early Responder",
    "late_riser":          "The Late Riser",
    "UNCLASSIFIED":        "The Explorer",
}

_PATTERN_SUMMARIES: dict[str, str] = {
    "over_optimizer": (
        "Nervous system is capable but chronically pushed — recovery trails effort."
    ),
    "sympathetic_dominant": (
        "Resting state tips toward activation — the system rarely fully switches off."
    ),
    "under_activator": (
        "The system has more capacity than it currently expresses — "
        "gentle progressive challenge will unlock it."
    ),
    "sleep_compromised": (
        "Recovery is bottlenecked overnight — sleep quality limits daytime readiness."
    ),
    "resilient_floor": (
        "Even at depletion the baseline holds — recovery is reliable once started."
    ),
    "early_responder": (
        "Morning is the system's strongest window — training before 10am yields the most."
    ),
    "late_riser": (
        "The system needs time to come online — afternoon windows consistently outperform morning."
    ),
    "UNCLASSIFIED": (
        "Not enough data to identify a pattern yet — building the baseline."
    ),
}

_STAGE_IN_WORDS: dict[int, str] = {
    0: "Stage 0 — just beginning, foundations being laid",
    1: "Stage 1 — recovery starting, first signals emerging",
    2: "Stage 2 — recovery building, pattern stabilising",
    3: "Stage 3 — recovery established, capacity growing",
    4: "Stage 4 — strong baseline, refining and consolidating",
    5: "Stage 5 — peak range, maintaining and challenging",
}


# ── CoachContext dataclass ────────────────────────────────────────────────────

@dataclass
class CoachContext:
    """
    The complete structured context fed to coaching prompt templates.

    This is the ONLY input the LLM receives about the user's physiology.
    All fields are strings or structured primitives — no raw floats.
    """

    # ── Identity ─────────────────────────────────────────────────────────────
    user_name:          str
    pattern_label:      str          # "The Over-Optimiser"
    pattern_summary:    str          # 1-sentence system description
    stage_in_words:     str          # "Stage 2 — recovery building, pattern stabilising"
    weeks_in_stage:     int

    # ── Today (personal-relative strings) ────────────────────────────────────
    today_rmssd_vs_avg:   str        # "-21% vs your average" | "at your average"
    today_rmssd_vs_floor: str        # "12% above your floor" | "at your floor"
    morning_read_quality: str        # "good" | "borderline" | "low"
    consecutive_low_days: int

    # ── 7-day trend ──────────────────────────────────────────────────────────
    score_7d_delta:        Optional[int]
    trajectory:            str          # "improving" | "stable" | "declining"
    load_trend:            str          # plain English summary
    sessions_this_week:    int
    last_session_ago_days: Optional[int]
    recovery_pattern_note: str          # "arcs completing in ~2.1hrs vs your 1.8hr avg"

    # ── Habit events (last 72h, specificity filtered) ────────────────────────
    recent_habit_events: list[str]   # ["alcohol event 2 nights ago (moderate)"]
    sleep_note:          str
    schedule_context:    str

    # ── Milestone ────────────────────────────────────────────────────────────
    milestone:          Optional[str]
    milestone_evidence: Optional[str]   # MUST contain a specific number, else None

    # ── Conversation memory ───────────────────────────────────────────────────
    last_user_said:       Optional[str]
    conversation_summary: Optional[str]  # max 300 words
    extracted_signals:    list[str]

    # ── Trigger + tone + prescription ────────────────────────────────────────
    trigger_type: str              # "morning_brief" | "post_session" | ...
    tone:         str              # pre-set by tone_selector
    prescription: DailyPrescription
    session_data: Optional[dict] = field(default_factory=lambda: None)

    # ── Today's scores (user-facing) ─────────────────────────────────────────
    # These are the ONLY numbers the coach cites in responses.
    # Raw metric values (RMSSD, RSA, etc.) must never reach the LLM.
    net_balance:     Optional[float] = field(default=None)  # unbounded ±; drives day colour
    stress_score:    Optional[int]   = field(default=None)  # 0–100
    recovery_score:  Optional[int]   = field(default=None)  # 0–100 (waking recovery)

    # ── Psychological profile insight ─────────────────────────────────────────
    psych_insight:   Optional[str] = field(default=None)   # pre-built 1-sentence insight

    # ── Unified User Profile — primary personality lens ───────────────────────
    # The full structured narrative from UserUnifiedProfile.coach_narrative.
    # Injected into morning_brief and conversation_turn prompts as the
    # PERSONALITY SNAPSHOT block. If None, personality block is omitted.
    uup_narrative:    Optional[str] = field(default=None)

    # Top durable conversation facts (from UserFact table, confidence >= 0.7).
    # Formatted as a flat list of strings for prompt injection.
    user_facts:       list[str]     = field(default_factory=list)

    # Facts extracted from the current user message only (same turn; may not be in DB yet).
    newly_extracted_facts: list[str] = field(default_factory=list)

    # Engagement tier from UUP — used by coach to calibrate push vs gentle.
    engagement_tier:  Optional[str] = field(default=None)  # "high"|"medium"|"low"|"at_risk"|"churned"

    # Avoid items from Layer 2 plan guardrails (Phase 3). Each dict has
    # "slug_or_label" and "reason" keys. Injected into TODAY'S PHYSIO block.
    avoid_items: list[dict] = field(default_factory=list)


# ── Public API ─────────────────────────────────────────────────────────────────

def build_coach_context(
    profile: NSHealthProfile,
    fingerprint: PersonalFingerprint,
    *,
    trigger_type: str,
    tone: str,
    prescription: DailyPrescription,
    user_name: str = "there",
    morning_rmssd_ms: Optional[float] = None,
    habit_signals: Optional[list[HabitSignal]] = None,
    consecutive_low_reads: int = 0,
    sessions_this_week: int = 0,
    last_session_ago_days: Optional[int] = None,
    milestone: Optional[str] = None,
    milestone_evidence: Optional[str] = None,
    last_user_said: Optional[str] = None,
    conversation_summary: Optional[str] = None,
    extracted_signals: Optional[list[str]] = None,
    session_data: Optional[dict] = None,
    schedule_note: str = "",
    net_balance:     Optional[float] = None,
    stress_score:    Optional[int] = None,
    recovery_score:  Optional[int] = None,
    psych_insight:   Optional[str] = None,
    uup_narrative:   Optional[str] = None,
    user_facts:      Optional[list[str]] = None,
    engagement_tier: Optional[str] = None,
    avoid_items:     Optional[list[dict]] = None,
    newly_extracted_facts: Optional[list[str]] = None,
) -> CoachContext:
    """
    Assemble a complete CoachContext for the given trigger.

    Parameters
    ----------
    profile : NSHealthProfile
        Current scoring output.
    fingerprint : PersonalFingerprint
        Personal baseline model — source of all reference frames.
    trigger_type : str
        "morning_brief" | "post_session" | "nudge" | "weekly_review" | "conversation_turn"
    tone : str
        Pre-selected by tone_selector. Injected without modification.
    prescription : DailyPrescription
        Output of plan_replanner.compute_daily_prescription().
    user_name : str
        Display name — not used for LLM decisions.
    morning_rmssd_ms : float | None
        Current morning RMSSD reading in milliseconds.
    habit_signals : list[HabitSignal] | None
        Signals from last 72 hours.
    consecutive_low_reads : int
        Consecutive below-floor morning reads.
    sessions_this_week : int
        Number of sessions completed this week.
    last_session_ago_days : int | None
        Days since last session.
    milestone : str | None
        Milestone label from milestone_detector, if fired.
    milestone_evidence : str | None
        Evidence string — MUST contain a specific digit or set to None.
    last_user_said : str | None
        Most recent user message — for conversation_turn trigger only.
    conversation_summary : str | None
        Rolling conversation summary, max 300 words.
    extracted_signals : list[str] | None
        Signals extracted from prior conversation by conversation_extractor.
    session_data : dict | None
        Post-session physiological summary — post_session trigger only.
    schedule_note : str
        Free-text schedule context (e.g. "travel day tomorrow").
    net_balance : float | None
        Net Balance (unbounded ±) — day colour + coach framing. Drives guardrails.
    stress_score : int | None
        0–100 Stress Load score — cited by coach in responses.
    recovery_score : int | None
        0–100 Waking Recovery score — cited by coach in responses.
    psych_insight : str | None
        Pre-built 1-sentence insight from PsychProfile.coach_insight.

    Returns
    -------
    CoachContext
    """
    hab = habit_signals or []
    extr = extracted_signals or []

    # ── RMSSD relative strings ────────────────────────────────────────────────
    rmssd_vs_avg_str, rmssd_vs_floor_str, read_quality = _build_rmssd_strings(
        morning_rmssd_ms, fingerprint
    )

    # ── Recovery arc note ─────────────────────────────────────────────────────
    recovery_note = _build_recovery_note(fingerprint)

    # ── Habit events (last 72h only, drop below-threshold) ───────────────────
    recent_events = _filter_habit_events(hab)

    # ── Sleep note ───────────────────────────────────────────────────────────
    sleep_note = _build_sleep_note(fingerprint)

    # ── 7-day load trend ─────────────────────────────────────────────────────
    load_trend = _build_load_trend(profile)

    # ── Pattern strings ───────────────────────────────────────────────────────
    pkey = profile.primary_pattern or "UNCLASSIFIED"
    pattern_label   = _PATTERN_LABELS.get(pkey, "The Explorer")
    pattern_summary = _PATTERN_SUMMARIES.get(pkey, _PATTERN_SUMMARIES["UNCLASSIFIED"])
    stage_str       = _STAGE_IN_WORDS.get(profile.stage, f"Stage {profile.stage}")

    # ── Milestone evidence safety check ──────────────────────────────────────
    # Evidence must contain a digit — blank it if not
    safe_evidence = _validate_milestone_evidence(milestone_evidence)

    # ── Conversation summary truncation ──────────────────────────────────────
    safe_summary = _truncate_summary(conversation_summary, max_words=300)

    return CoachContext(
        user_name              = user_name,
        pattern_label          = pattern_label,
        pattern_summary        = pattern_summary,
        stage_in_words         = stage_str,
        weeks_in_stage         = profile.weeks_in_stage,

        today_rmssd_vs_avg     = rmssd_vs_avg_str,
        today_rmssd_vs_floor   = rmssd_vs_floor_str,
        morning_read_quality   = read_quality,
        consecutive_low_days   = consecutive_low_reads,

        score_7d_delta         = profile.score_7d_delta,
        trajectory             = profile.trajectory,
        load_trend             = load_trend,
        sessions_this_week     = sessions_this_week,
        last_session_ago_days  = last_session_ago_days,
        recovery_pattern_note  = recovery_note,

        recent_habit_events    = recent_events,
        sleep_note             = sleep_note,
        schedule_context       = schedule_note or "none reported",

        milestone              = milestone,
        milestone_evidence     = safe_evidence,

        last_user_said         = last_user_said,
        conversation_summary   = safe_summary,
        extracted_signals      = extr,

        trigger_type           = trigger_type,
        tone                   = tone,
        prescription           = prescription,
        session_data           = session_data,
        net_balance            = net_balance,
        stress_score           = stress_score,
        recovery_score         = recovery_score,
        psych_insight          = psych_insight,
        uup_narrative          = uup_narrative,
        user_facts             = user_facts or [],
        engagement_tier        = engagement_tier,
        avoid_items            = avoid_items or [],
        newly_extracted_facts  = newly_extracted_facts or [],
    )


# ── Private helpers ────────────────────────────────────────────────────────────

def _build_rmssd_strings(
    morning_rmssd_ms: Optional[float],
    fp: PersonalFingerprint,
) -> tuple[str, str, str]:
    """
    Convert raw RMSSD to personal-relative strings.

    Returns
    -------
    (vs_avg_str, vs_floor_str, quality_label)
    """
    if morning_rmssd_ms is None or not fp.is_ready():
        return "reading unavailable", "reading unavailable", "unknown"

    # vs daily average
    avg = fp.rmssd_morning_avg
    if avg and avg > 0:
        pct_from_avg = (morning_rmssd_ms - avg) / avg
        vs_avg = _pct_str(pct_from_avg, reference="your average")
    else:
        vs_avg = "average unavailable"

    # vs personal floor
    floor = fp.rmssd_floor
    if floor and floor > 0:
        pct_from_floor = (morning_rmssd_ms - floor) / floor
        vs_floor = _pct_str(pct_from_floor, reference="your floor", above_label="above", below_label="below")

        # quality label
        if pct_from_floor >= 0.05:
            quality = "good"
        elif pct_from_floor >= -0.05:
            quality = "borderline"
        else:
            quality = "low"
    else:
        vs_floor = "floor unavailable"
        quality = "unknown"

    return vs_avg, vs_floor, quality


def _pct_str(
    delta: float,
    *,
    reference: str = "your average",
    above_label: str = "above",
    below_label: str = "below",
) -> str:
    """
    Convert a fractional delta to a plain-language percentage string.

    Examples:
        -0.21 → "-21% vs your average"
        +0.12 → "12% above your floor"
         0.00 → "at your average"
    """
    abs_pct = abs(delta) * 100
    if abs_pct < 1.0:
        return f"at {reference}"
    if delta < 0:
        return f"-{abs_pct:.0f}% {below_label} {reference}"
    return f"+{abs_pct:.0f}% {above_label} {reference}"


def _build_recovery_note(fp: PersonalFingerprint) -> str:
    """
    Build personal arc comparison note.

    If recent arc data is available: "arcs completing in ~2.4hrs vs your 1.8hr average"
    If only average available: "your typical arc completes in ~1.8hrs"
    """
    mean = fp.recovery_arc_mean_hours
    fast = fp.recovery_arc_fast_hours
    slow = fp.recovery_arc_slow_hours

    if mean is None:
        return "recovery arc data not yet established"

    note = f"your typical arc completes in ~{mean:.1f}hrs"
    if fast is not None and slow is not None:
        note += f" (fast: {fast:.1f}hrs, slow: {slow:.1f}hrs)"
    return note


def _filter_habit_events(signals: list[HabitSignal]) -> list[str]:
    """
    Convert HabitSignal list to plain-language strings.
    Only include events from the last 72 hours.
    Drops positive_state signals (not load-relevant for narrative).
    """
    results: list[str] = []
    for sig in signals:
        if sig.hours_ago > 72.0:
            continue
        if sig.event_type == "positive_state":
            continue
        label = _habit_event_label(sig)
        if label:
            results.append(label)
    return results


def _habit_event_label(sig: HabitSignal) -> str:
    """Convert a HabitSignal to a plain-English label."""
    hours = sig.hours_ago
    if hours < 16:
        when = "today"
    elif hours < 32:
        when = "last night" if sig.event_type in {"alcohol", "late_night"} else "yesterday"
    elif hours < 56:
        when = "2 nights ago" if sig.event_type in {"alcohol", "late_night"} else "2 days ago"
    else:
        when = "3 days ago"

    sev = sig.severity

    labels: dict[str, str] = {
        "alcohol":          f"alcohol ({sev}) {when}",
        "late_night":       f"late night {when}",
        "stressful_event":  f"reported stressor {when}",
        "exercise_heavy":   f"heavy training {when}",
        "missed_session":   f"session skipped {when}",
        "schedule_constraint": f"schedule constraint {when}",
    }
    return labels.get(sig.event_type, f"{sig.event_type} ({sev}) {when}")


def _build_sleep_note(fp: PersonalFingerprint) -> str:
    """
    Build sleep quality note from PersonalFingerprint proxies.
    Uses overnight RMSSD delta as the sleep recovery proxy.
    """
    eff = fp.sleep_recovery_efficiency
    delta = fp.overnight_rmssd_delta_avg

    if eff is None:
        return "sleep data not yet established"

    if eff >= 1.15:
        note = "overnight recovery looks solid"
    elif eff >= 0.95:
        note = "overnight recovery is moderate"
    else:
        note = "overnight recovery is low"

    if delta is not None:
        direction = "up" if delta > 0 else "down"
        note += f" (morning RMSSD typically {direction} {abs(delta):.0f}% overnight)"

    return note


def _build_load_trend(profile: NSHealthProfile) -> str:
    """
    Build a plain-English weekly load trend from profile fields.
    """
    traj = profile.trajectory
    d7   = profile.score_7d_delta

    if traj == "improving":
        if d7 is not None and d7 >= 5:
            return f"improving — up {d7} points this week"
        return "gradually improving over the past week"
    if traj == "declining":
        if d7 is not None and d7 <= -3:
            return f"under pressure — down {abs(d7)} points this week"
        return "slightly under pressure this week"
    return "holding steady this week"


def _validate_milestone_evidence(evidence: Optional[str]) -> Optional[str]:
    """
    Milestone evidence must contain at least one digit.
    If it doesn't, return None — the schema_validator will also check this.
    """
    if evidence is None:
        return None
    # Accept if any digit character present
    if any(ch.isdigit() for ch in evidence):
        return evidence
    return None


def _truncate_summary(text: Optional[str], max_words: int = 300) -> Optional[str]:
    """
    Truncate conversation summary to max_words.
    """
    if text is None:
        return None
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + " …"
