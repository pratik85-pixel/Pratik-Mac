"""
coach/plan_replanner.py

Daily plan prescription — recomputed every morning from current state.

Design:
    There is no stored weekly plan document. Every morning when a morning read
    arrives, this module runs completely fresh and produces a DailyPrescription.

    The prescription defines what kind of session the user should do today,
    at what intensity, and in what window. The LLM does not choose any of this —
    it only translates the reason_tag into human language.

    The `stage_focus` from NSHealthProfile is the structural ceiling.
    The current state (load_score) is the floor.
    The prescription lives between them.

Load score:
    A composite 0.0–1.0 pressure index computed from stacked lifestyle signals.
    ≥ 0.65 → rest
    ≥ 0.40 → breathing_only
    else   → stage-appropriate at adjusted intensity

Habit event types accepted:
    "alcohol"             — drink event (severity: light | moderate | heavy)
    "late_night"          — sleep window pushed past midnight
    "stressful_event"     — reported or extracted stress flag
    "exercise_heavy"      — intense physical session logged
    "missed_session"      — session due but not completed
    "positive_state"      — user reported feeling good + HRV green
    "schedule_constraint" — user flagged time pressure

References:
    NSHealthProfile from archetypes/scorer.py
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from archetypes.scorer import NSHealthProfile
from sessions.practice_registry import VALID_PRACTICE_TYPES


# ── Output type ───────────────────────────────────────────────────────────────

@dataclass
class DailyPrescription:
    """
    The day's coaching prescription.

    Computed deterministically from current-state signals.
    Fed to context_builder → LLM writes the human version.
    """
    session_type:       str            # "breathing_only" | "full" | "active_recovery" | "rest"
    session_duration:   int            # minutes
    session_intensity:  str            # "low" | "moderate" | "high"
    session_window:     str            # preferred time band, e.g. "19:00–21:00"
    physical_load:      str            # "reduce" | "maintain" | "can_increase"
    load_score:         float          # 0.0–1.0 composite pressure
    reason_tag:         str            # drives context template, e.g. "alcohol_recovery_compound"
    carry_forward:      bool = False   # missed session that should be carried to tomorrow
    notes:              list[str] = field(default_factory=list)  # optional coach notes
    # ── Practice layer (populated by session_prescriber after plan is computed) ──
    practice_type:      str = "resonance_hold"   # see sessions/practice_registry.py
    attention_anchor:   Optional[str] = None      # "belly" | "heart" | "solar" | "root" | "brow"


@dataclass
class HabitSignal:
    """Single lifestyle signal — from conversation extract, Apple Health, or manual log."""
    event_type:     str            # see module docstring for valid types
    severity:       str = "moderate"   # "light" | "moderate" | "heavy"
    hours_ago:      float = 0.0    # how long ago the event occurred
    source:         str = "conversation"  # "conversation" | "apple_health" | "manual"


# ── Public API ─────────────────────────────────────────────────────────────────

def compute_daily_prescription(
    profile: NSHealthProfile,
    morning_rmssd_vs_floor: Optional[float] = None,   # e.g. 0.12 = 12% above floor
    morning_rmssd_vs_avg: Optional[float] = None,     # e.g. -0.21 = 21% below avg
    consecutive_low_reads: int = 0,
    habit_signals: Optional[list[HabitSignal]] = None,
    preferred_window_hour: Optional[int] = None,      # from PersonalFingerprint.best_window_hour
    sessions_this_week: int = 0,
) -> DailyPrescription:
    """
    Compute today's DailyPrescription from current state.

    Parameters
    ----------
    profile : NSHealthProfile
        Current scoring profile — used for stage + pattern context.
    morning_rmssd_vs_floor : float | None
        Fractional delta vs personal floor. 0.12 = 12% above floor. None = unknown.
    morning_rmssd_vs_avg : float | None
        Fractional delta vs personal average. -0.21 = 21% below average. None = unknown.
    consecutive_low_reads : int
        How many consecutive below-floor morning reads have been recorded.
    habit_signals : list[HabitSignal] | None
        Recent lifestyle events (last 72 hours).
    preferred_window_hour : int | None
        User's best session window hour from PersonalFingerprint.
    sessions_this_week : int
        Sessions completed so far this week.

    Returns
    -------
    DailyPrescription
    """
    signals = habit_signals or []

    load_score = _compute_load_score(
        morning_rmssd_vs_floor=morning_rmssd_vs_floor,
        morning_rmssd_vs_avg=morning_rmssd_vs_avg,
        consecutive_low_reads=consecutive_low_reads,
        habit_signals=signals,
    )

    reason_tag = _determine_reason_tag(
        load_score=load_score,
        habit_signals=signals,
        profile=profile,
        consecutive_low_reads=consecutive_low_reads,
    )

    session_window = _compute_session_window(
        preferred_window_hour=preferred_window_hour,
        profile=profile,
    )

    return _build_prescription(
        profile=profile,
        load_score=load_score,
        reason_tag=reason_tag,
        session_window=session_window,
        sessions_this_week=sessions_this_week,
        habit_signals=signals,
    )


# ── Load score ─────────────────────────────────────────────────────────────────

def _compute_load_score(
    morning_rmssd_vs_floor: Optional[float],
    morning_rmssd_vs_avg: Optional[float],
    consecutive_low_reads: int,
    habit_signals: list[HabitSignal],
) -> float:
    """
    Composite 0.0–1.0 pressure index.

    Higher = more physiological pressure = less capacity for load today.

    Weight breakdown:
      alcohol_within_24h     0.30
      below_floor_severity   0.35  (most sensitive personal signal)
      consecutive_low_reads  0.20
      weekly_load_signals    0.15
    """
    score = 0.0

    # ── Alcohol within 24h ──────────────────────────────────────────────────
    alcohol = [s for s in habit_signals if s.event_type == "alcohol" and s.hours_ago <= 24]
    if alcohol:
        worst = max(alcohol, key=lambda s: {"light": 1, "moderate": 2, "heavy": 3}.get(s.severity, 1))
        score += 0.30 * {"light": 0.5, "moderate": 0.85, "heavy": 1.0}.get(worst.severity, 0.5)

    # ── Below-floor severity ─────────────────────────────────────────────────
    if morning_rmssd_vs_floor is not None:
        if morning_rmssd_vs_floor < -0.20:    # > 20% below floor — very depleted
            score += 0.35
        elif morning_rmssd_vs_floor < -0.10:  # 10–20% below floor
            score += 0.20
        elif morning_rmssd_vs_floor < 0:      # marginally below floor
            score += 0.10
    elif morning_rmssd_vs_avg is not None:
        # Fallback: use avg comparison if floor not available
        if morning_rmssd_vs_avg < -0.25:
            score += 0.25
        elif morning_rmssd_vs_avg < -0.15:
            score += 0.15

    # ── Consecutive low reads ────────────────────────────────────────────────
    if consecutive_low_reads >= 3:
        score += 0.20
    elif consecutive_low_reads == 2:
        score += 0.12
    elif consecutive_low_reads == 1:
        score += 0.05

    # ── Weekly load signals ──────────────────────────────────────────────────
    stress_events = [s for s in habit_signals if s.event_type == "stressful_event"]
    late_nights   = [s for s in habit_signals if s.event_type == "late_night" and s.hours_ago <= 48]
    heavy_ex      = [s for s in habit_signals if s.event_type == "exercise_heavy" and s.hours_ago <= 24]

    weekly_pressure = 0.0
    if stress_events:
        weekly_pressure += 0.5
    if late_nights:
        weekly_pressure += 0.3
    if heavy_ex:
        weekly_pressure += 0.3
    score += 0.15 * min(1.0, weekly_pressure)

    # ── Positive state override ──────────────────────────────────────────────
    # Confirmed positive state + no alcohol/low-read signals → partial reduction
    positive = [s for s in habit_signals if s.event_type == "positive_state"]
    if positive and score < 0.30:
        score *= 0.70   # reduce pressure by 30% when user explicitly reports feeling good

    return round(min(1.0, score), 3)


# ── Reason tag ─────────────────────────────────────────────────────────────────

def _determine_reason_tag(
    load_score: float,
    habit_signals: list[HabitSignal],
    profile: NSHealthProfile,
    consecutive_low_reads: int,
) -> str:
    """
    Derive the reason_tag that context_builder uses to populate the coaching explanation.

    The tag is a specific identifier — not a generic label.
    The LLM translates it; never invents the reason.
    """
    has_alcohol = any(s.event_type == "alcohol" and s.hours_ago <= 24 for s in habit_signals)
    has_stress  = any(s.event_type == "stressful_event" for s in habit_signals)
    has_late    = any(s.event_type == "late_night" and s.hours_ago <= 48 for s in habit_signals)
    has_missed  = any(s.event_type == "missed_session" for s in habit_signals)
    has_heavy   = any(s.event_type == "exercise_heavy" and s.hours_ago <= 24 for s in habit_signals)

    # Compound tags (stacked signals) take priority
    if has_alcohol and consecutive_low_reads >= 2:
        return "alcohol_recovery_compound"
    if has_stress and consecutive_low_reads >= 2:
        return "chronic_load_compound"
    if has_alcohol and has_late:
        return "alcohol_late_night_compound"

    # Single dominant signal
    if has_alcohol:
        return "alcohol_recovery"
    if consecutive_low_reads >= 3:
        return "sustained_depletion"
    if consecutive_low_reads >= 2:
        return "consecutive_low_reads"
    if has_stress:
        return "reported_stress"
    if has_late:
        return "late_night_recovery"
    if has_heavy:
        return "post_exercise_recovery"
    if has_missed:
        return "carry_forward_session"
    if load_score < 0.15:
        return "optimal_state"
    if load_score < 0.35:
        return "stage_progression"

    return f"stage_{profile.stage}_standard"


# ── Prescription builder ───────────────────────────────────────────────────────

def _build_prescription(
    profile: NSHealthProfile,
    load_score: float,
    reason_tag: str,
    session_window: str,
    sessions_this_week: int,
    habit_signals: list[HabitSignal],
) -> DailyPrescription:
    """
    Map load_score + stage + signals → DailyPrescription.

    The stage_focus from NSHealthProfile is the direction (what we're building).
    The load_score determines how much of it the body can accept today.
    """
    missed = any(s.event_type == "missed_session" for s in habit_signals)
    positive = any(s.event_type == "positive_state" for s in habit_signals)
    stage = profile.stage

    # ── High pressure: rest or minimal ────────────────────────────────────────
    if load_score >= 0.65:
        return DailyPrescription(
            session_type      = "rest",
            session_duration  = 0,
            session_intensity = "low",
            session_window    = session_window,
            physical_load     = "reduce",
            load_score        = load_score,
            reason_tag        = reason_tag,
            carry_forward     = sessions_this_week < _weekly_target(stage),
            notes             = ["Body is in active recovery. Rest is the prescription."],
        )

    if load_score >= 0.40:
        return DailyPrescription(
            session_type      = "breathing_only",
            session_duration  = 10,
            session_intensity = "low",
            session_window    = session_window,
            physical_load     = "reduce",
            load_score        = load_score,
            reason_tag        = reason_tag,
            carry_forward     = sessions_this_week < _weekly_target(stage),
            notes             = ["Minimum effective dose — breathing only, no physical load."],
        )

    # ── Moderate pressure: reduced version of stage plan ─────────────────────
    if load_score >= 0.20:
        base_dur, base_int = _stage_base(stage)
        return DailyPrescription(
            session_type      = "full" if stage >= 2 else "breathing_only",
            session_duration  = max(10, int(base_dur * 0.70)),
            session_intensity = "low",
            session_window    = session_window,
            physical_load     = "maintain",
            load_score        = load_score,
            reason_tag        = reason_tag,
        )

    # ── Low pressure: full stage plan ────────────────────────────────────────
    base_dur, base_int = _stage_base(stage)

    # Green + positive → can increase if capacity present
    if positive and profile.recovery_capacity >= 12 and profile.load_management >= 12:
        physical_load = "can_increase"
    else:
        physical_load = "maintain"

    return DailyPrescription(
        session_type      = _stage_session_type(stage),
        session_duration  = base_dur,
        session_intensity = base_int,
        session_window    = session_window,
        physical_load     = physical_load,
        load_score        = load_score,
        reason_tag        = reason_tag,
        notes             = (["Carry-forward from missed session."] if missed else []),
    )


# ── Stage helpers ──────────────────────────────────────────────────────────────

def _stage_base(stage: int) -> tuple[int, str]:
    """(duration_minutes, intensity) for each stage's standard session."""
    _map = {
        0: (5,  "low"),
        1: (10, "low"),
        2: (15, "moderate"),
        3: (20, "moderate"),
        4: (25, "moderate"),
        5: (30, "high"),
    }
    return _map.get(stage, (10, "low"))


def _stage_session_type(stage: int) -> str:
    if stage <= 1:
        return "breathing_only"
    if stage <= 3:
        return "full"
    return "full"


def _weekly_target(stage: int) -> int:
    """Minimum sessions per week for the given stage."""
    return {0: 3, 1: 4, 2: 5, 3: 5, 4: 6, 5: 6}.get(stage, 4)


def _compute_session_window(
    preferred_window_hour: Optional[int],
    profile: NSHealthProfile,
) -> str:
    """Return a human-readable session time window string."""
    if preferred_window_hour is None:
        # Default: evening — safe for all patterns
        return "19:00–21:00"

    h = preferred_window_hour
    end = (h + 2) % 24
    return f"{h:02d}:00–{end:02d}:00"
