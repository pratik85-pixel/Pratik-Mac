"""
coach/assessor.py

User assessment module.

Synthesises multiple data streams into a structured UserAssessment that
drives coaching decisions and level gate evaluation.

Three responsibilities
----------------------
1. Level gate evaluation using the 3-gate system (DESIGN_V2 Section 12):
       Gate 1 — Adherence   ≥ 60% of last 10 prescribed sessions completed
       Gate 2 — Readiness trend  14-day rolling avg ≥ prev 14-day avg + 5 pts
       Gate 3 — Session quality  avg score ≥ 0.25 (soft — triggers conversation)
       Floor  — Minimum session count (safety only, not primary gate)

2. Learning state classification:
       improving | stabilizing | plateaued | declining

3. Deviation pattern analysis:
       Identifies recurring deviation reason_categories → notifies prescriber.

The existing outcomes/level_gate.py implements the prior physiological-gate
system. The assessor replaces it for all new advancement logic. Old
level_gate.py is preserved for backwards-compatible recompute tasks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ── Constants ─────────────────────────────────────────────────────────────────

# Gate 1
ADHERENCE_WINDOW:      int   = 10     # last N prescribed sessions
ADHERENCE_THRESHOLD:   float = 0.60   # 60%

# Gate 2
READINESS_WINDOW_DAYS:     int   = 14
READINESS_IMPROVEMENT_PTS: float = 5.0

# Gate 3 (soft check)
SESSION_QUALITY_THRESHOLD: float = 0.25

# Minimum session floor per transition (safety only)
MIN_SESSION_FLOOR: dict[int, int] = {0: 2, 1: 6, 2: 12, 3: 18, 4: 24}

# Learning state thresholds
IMPROVING_DELTA:     float = 3.0    # readiness trending up ≥ 3 pts vs prior 7-day
DECLINING_DELTA:     float = -3.0   # readiness trending down ≥ 3 pts
PLATEAU_DAYS:        int   = 14     # considered plateaued if no sig change in N days

# Deviation recurrence threshold (prescriber feedback)
DEVIATION_RECURRENCE: int = 3       # same reason_category N+ times → flag


# ── Input types ───────────────────────────────────────────────────────────────

@dataclass
class SessionRecord:
    """Minimal session record for assessment purposes."""
    session_id:    str
    session_score: Optional[float]   # 0–100 normalised to 0.0–1.0 by assessor
    was_prescribed: bool             # True if this session appeared in a DailyPlan
    completed:     bool              # True if the session was actually completed


@dataclass
class ReadinessRecord:
    """Daily readiness score record."""
    date_index: int    # 0 = oldest, ascending order
    readiness:  float  # 0–100


@dataclass
class DeviationRecord:
    """A single PlanDeviation record for analysis."""
    activity_slug:   str
    priority:        str          # "must_do" | "recommended" | "optional"
    reason_category: Optional[str]


@dataclass
class ConversationSignal:
    """
    Extracted conversation signal that may affect assessment.

    signal_label — plain English label from ConversationState.accumulated_signals
    days_ago     — how many days ago the signal was extracted
    """
    signal_label: str
    days_ago:     int = 0


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class GateStatus:
    """Result of a single gate check."""
    name:     str
    passed:   bool
    value:    Optional[float]   # computed metric value
    threshold: Optional[float]  # threshold it was compared to
    note:     str               # human-readable note for coach context


@dataclass
class LevelGateResult:
    """
    New 3-gate level advancement result.

    ready            — True only when ALL gates pass AND floor is met.
    current_stage    — User's current stage (0–5).
    next_stage       — None if already at stage 5.
    gate_1_adherence — Gate 1 status.
    gate_2_readiness — Gate 2 status.
    gate_3_quality   — Gate 3 status (soft — not a hard block).
    floor_met        — True if minimum session count is satisfied.
    suppressed_by    — Conversation signal labels that vetoed advancement.
    criteria_met     — dict[str, bool] for all named criteria (backward compat.).
    blocking         — Plain English list of unmet hard gates.
    """
    ready:            bool
    current_stage:    int
    next_stage:       Optional[int]
    gate_1_adherence: GateStatus
    gate_2_readiness: GateStatus
    gate_3_quality:   GateStatus
    floor_met:        bool
    suppressed_by:    list[str]
    criteria_met:     dict[str, bool]
    blocking:         list[str]


@dataclass
class UserAssessment:
    """
    Complete assessment of a user's current state.

    level_gate       — Level advancement eligibility.
    learning_state   — "improving" | "stabilizing" | "plateaued" | "declining"
    adherence_7d:    dict — {category: pct} adherence over last 7 days per category.
    recurring_deviations — reason_categories that recurred DEVIATION_RECURRENCE+ times.
    total_sessions   — Total qualifying sessions in history.
    sport_stressors  — From TagPatternModel — sports known to drive high stress.
    summary_note     — Single sentence for CoachContext injection.
    """
    level_gate:           LevelGateResult
    learning_state:       str
    adherence_7d:         dict[str, float]
    recurring_deviations: list[str]
    total_sessions:       int
    sport_stressors:      list[str]
    summary_note:         str


# ── Public API ─────────────────────────────────────────────────────────────────

def assess_user(
    current_stage: int,
    session_records: list[SessionRecord],
    readiness_records: list[ReadinessRecord],
    deviation_records: Optional[list[DeviationRecord]] = None,
    conversation_signals: Optional[list[ConversationSignal]] = None,
    adherence_by_category: Optional[dict[str, float]] = None,
    sport_stressors: Optional[list[str]] = None,
) -> UserAssessment:
    """
    Run the full user assessment.

    Parameters
    ----------
    current_stage : int
        User's current NS-health stage (0–5).
    session_records : list[SessionRecord]
        All qualifying sessions in chronological order (oldest first).
        Should include at least the last 10 prescribed sessions.
    readiness_records : list[ReadinessRecord]
        Daily readiness scores in chronological order (oldest first).
        Should span at least 28 days for Gate 2 evaluation.
    deviation_records : list[DeviationRecord] | None
        Recent plan deviations (last 30 days).
    conversation_signals : list[ConversationSignal] | None
        Accumulated conversation signals that may suppress advancement.
    adherence_by_category : dict[str, float] | None
        Pre-computed adherence per category (0.0–1.0) over last 7 days.
        If None, computed from session_records (zenflow_session category only).
    sport_stressors : list[str] | None
        From UserTagPatternModel.sport_stressor_slugs.

    Returns
    -------
    UserAssessment
    """
    gate_result = _evaluate_level_gate(
        current_stage=current_stage,
        session_records=session_records,
        readiness_records=readiness_records,
        conversation_signals=conversation_signals or [],
    )

    learning_state = _classify_learning_state(readiness_records)

    recurring = _find_recurring_deviations(deviation_records or [])

    adh = adherence_by_category or _compute_session_adherence(session_records)

    total_sessions = sum(1 for s in session_records if s.completed)

    note = _build_summary_note(
        gate_result=gate_result,
        learning_state=learning_state,
        current_stage=current_stage,
        recurring_deviations=recurring,
    )

    return UserAssessment(
        level_gate=gate_result,
        learning_state=learning_state,
        adherence_7d=adh,
        recurring_deviations=recurring,
        total_sessions=total_sessions,
        sport_stressors=sport_stressors or [],
        summary_note=note,
    )


def evaluate_level_gate(
    current_stage: int,
    session_records: list[SessionRecord],
    readiness_records: list[ReadinessRecord],
    conversation_signals: Optional[list[ConversationSignal]] = None,
) -> LevelGateResult:
    """Standalone level gate evaluation without full user assessment."""
    return _evaluate_level_gate(
        current_stage=current_stage,
        session_records=session_records,
        readiness_records=readiness_records,
        conversation_signals=conversation_signals or [],
    )


# ── Gate evaluations ──────────────────────────────────────────────────────────

def _evaluate_level_gate(
    current_stage: int,
    session_records: list[SessionRecord],
    readiness_records: list[ReadinessRecord],
    conversation_signals: list[ConversationSignal],
) -> LevelGateResult:
    if current_stage >= 5:
        no_gate = GateStatus(name="", passed=False, value=None, threshold=None, note="")
        return LevelGateResult(
            ready=False, current_stage=5, next_stage=None,
            gate_1_adherence=no_gate, gate_2_readiness=no_gate,
            gate_3_quality=no_gate, floor_met=False,
            suppressed_by=[], criteria_met={}, blocking=[],
        )

    next_stage = current_stage + 1

    # Gate 1 — Adherence
    gate_1 = _gate_1_adherence(session_records)

    # Gate 2 — Readiness trend
    gate_2 = _gate_2_readiness(readiness_records)

    # Gate 3 — Session quality (soft)
    gate_3 = _gate_3_quality(session_records)

    # Minimum session floor
    completed_count = sum(1 for s in session_records if s.completed)
    floor = MIN_SESSION_FLOOR.get(current_stage, 0)
    floor_met = completed_count >= floor

    # Conversation signal suppression (can only suppress, never trigger)
    suppressed_by = _check_suppression(conversation_signals)

    # Hard blockers: Gate 1 + Gate 2 + floor (Gate 3 is soft)
    blocking: list[str] = []
    if not floor_met:
        blocking.append(
            f"Need {floor} sessions completed (have {completed_count})"
        )
    if not gate_1.passed:
        blocking.append(gate_1.note)
    if not gate_2.passed:
        blocking.append(gate_2.note)
    if suppressed_by:
        blocking.append(
            f"Coach hold: {', '.join(suppressed_by)}"
        )

    ready = (
        floor_met
        and gate_1.passed
        and gate_2.passed
        and not suppressed_by
        # Gate 3 is soft — does not block ready
    )

    criteria_met = {
        "floor_met":           floor_met,
        "adherence":           gate_1.passed,
        "readiness_trend":     gate_2.passed,
        "session_quality":     gate_3.passed,
        "no_suppression":      not bool(suppressed_by),
    }

    return LevelGateResult(
        ready=ready,
        current_stage=current_stage,
        next_stage=next_stage,
        gate_1_adherence=gate_1,
        gate_2_readiness=gate_2,
        gate_3_quality=gate_3,
        floor_met=floor_met,
        suppressed_by=suppressed_by,
        criteria_met=criteria_met,
        blocking=blocking,
    )


def _gate_1_adherence(session_records: list[SessionRecord]) -> GateStatus:
    """
    Gate 1: ≥ 60% of last 10 prescribed sessions completed.
    """
    prescribed = [s for s in session_records if s.was_prescribed]
    last_10 = prescribed[-ADHERENCE_WINDOW:]
    if not last_10:
        return GateStatus(
            name="adherence",
            passed=False,
            value=0.0,
            threshold=ADHERENCE_THRESHOLD,
            note="No prescribed sessions found in history.",
        )
    completed = sum(1 for s in last_10 if s.completed)
    pct = completed / len(last_10)
    passed = pct >= ADHERENCE_THRESHOLD
    return GateStatus(
        name="adherence",
        passed=passed,
        value=round(pct, 3),
        threshold=ADHERENCE_THRESHOLD,
        note=(
            f"Completed {completed}/{len(last_10)} prescribed sessions "
            f"({round(pct * 100)}% vs {round(ADHERENCE_THRESHOLD * 100)}% required)."
            if not passed else
            f"Adherence gate passed: {round(pct * 100)}%."
        ),
    )


def _gate_2_readiness(readiness_records: list[ReadinessRecord]) -> GateStatus:
    """
    Gate 2: 14-day rolling avg readiness ≥ prior 14-day avg + 5 pts.
    Requires at least 28 readiness records.
    """
    if len(readiness_records) < READINESS_WINDOW_DAYS * 2:
        return GateStatus(
            name="readiness_trend",
            passed=False,
            value=None,
            threshold=None,
            note=(
                f"Need {READINESS_WINDOW_DAYS * 2} days of readiness data "
                f"(have {len(readiness_records)})."
            ),
        )

    recent = readiness_records[-READINESS_WINDOW_DAYS:]
    prior  = readiness_records[-READINESS_WINDOW_DAYS * 2:-READINESS_WINDOW_DAYS]

    recent_avg = sum(r.readiness for r in recent) / len(recent)
    prior_avg  = sum(r.readiness for r in prior) / len(prior)
    delta      = recent_avg - prior_avg

    passed = delta >= READINESS_IMPROVEMENT_PTS
    return GateStatus(
        name="readiness_trend",
        passed=passed,
        value=round(delta, 2),
        threshold=READINESS_IMPROVEMENT_PTS,
        note=(
            f"Readiness up {round(delta, 1)} pts vs prior 14 days "
            f"(need +{READINESS_IMPROVEMENT_PTS})."
            if passed else
            f"Readiness delta {round(delta, 1)} pts — need +{READINESS_IMPROVEMENT_PTS}."
        ),
    )


def _gate_3_quality(session_records: list[SessionRecord]) -> GateStatus:
    """
    Gate 3 (soft): average session score ≥ 0.25 across qualifying sessions.
    Not a hard block — triggers a coach conversation if failing.
    """
    scored = [
        s.session_score for s in session_records
        if s.completed and s.session_score is not None
    ]
    if not scored:
        return GateStatus(
            name="session_quality",
            passed=True,  # no data → don't penalise
            value=None,
            threshold=SESSION_QUALITY_THRESHOLD,
            note="No scored sessions available.",
        )

    # Normalise: session_score assumed 0–100; compare at 0.0–1.0 scale
    avg = sum(scored) / len(scored)
    avg_normalised = avg / 100.0 if avg > 1.0 else avg

    passed = avg_normalised >= SESSION_QUALITY_THRESHOLD
    return GateStatus(
        name="session_quality",
        passed=passed,
        value=round(avg_normalised, 3),
        threshold=SESSION_QUALITY_THRESHOLD,
        note=(
            f"Session quality avg {round(avg_normalised, 2)} "
            f"({'soft check — conversation recommended' if not passed else 'OK'})."
        ),
    )


def _check_suppression(signals: list[ConversationSignal]) -> list[str]:
    """
    Identify conversation signals that should suppress advancement.

    Suppression triggers: signals that indicate overwhelm, distress, or
    explicit user pushback in the last 7 days.
    """
    _SUPPRESSION_KEYWORDS = {
        "overwhelmed", "too much", "not ready", "overwhelm",
        "burned out", "burnout", "stressed", "struggling",
        "can't keep up", "too hard", "too intense",
    }
    recent = [s for s in signals if s.days_ago <= 7]
    suppressed: list[str] = []
    for sig in recent:
        label_lower = sig.signal_label.lower()
        if any(kw in label_lower for kw in _SUPPRESSION_KEYWORDS):
            suppressed.append(sig.signal_label)
    return suppressed


# ── Learning state ────────────────────────────────────────────────────────────

def _classify_learning_state(readiness_records: list[ReadinessRecord]) -> str:
    """
    Classify the user's learning trajectory from recent readiness trends.

    Returns one of: "improving" | "stabilizing" | "plateaued" | "declining"
    """
    if len(readiness_records) < 7:
        return "stabilizing"

    recent_7  = readiness_records[-7:]
    prior_7   = readiness_records[-14:-7] if len(readiness_records) >= 14 else readiness_records[:7]

    recent_avg = sum(r.readiness for r in recent_7) / len(recent_7)
    prior_avg  = sum(r.readiness for r in prior_7) / len(prior_7)
    delta      = recent_avg - prior_avg

    if delta >= IMPROVING_DELTA:
        return "improving"
    if delta <= DECLINING_DELTA:
        return "declining"

    # Check for plateau: no significant change over PLATEAU_DAYS
    if len(readiness_records) >= PLATEAU_DAYS:
        all_recent = readiness_records[-PLATEAU_DAYS:]
        values = [r.readiness for r in all_recent]
        spread = max(values) - min(values)
        if spread < 10.0:   # less than 10 point range = plateau
            return "plateaued"

    return "stabilizing"


# ── Deviation analysis ────────────────────────────────────────────────────────

def _find_recurring_deviations(deviations: list[DeviationRecord]) -> list[str]:
    """
    Return reason_categories that recur >= DEVIATION_RECURRENCE times.

    These signal a systematic mismatch between the plan and the user's life,
    prompting the prescriber to adjust accordingly.
    """
    counts: dict[str, int] = {}
    for d in deviations:
        if d.reason_category:
            counts[d.reason_category] = counts.get(d.reason_category, 0) + 1
    return [rc for rc, count in counts.items() if count >= DEVIATION_RECURRENCE]


# ── Adherence fallback ────────────────────────────────────────────────────────

def _compute_session_adherence(session_records: list[SessionRecord]) -> dict[str, float]:
    """
    Compute adherence pct for zenflow_session category from session records.
    Returns {"zenflow_session": pct}.
    """
    prescribed = [s for s in session_records if s.was_prescribed]
    if not prescribed:
        return {"zenflow_session": 0.0}
    completed = sum(1 for s in prescribed if s.completed)
    return {"zenflow_session": round(completed / len(prescribed), 3)}


# ── Summary note ──────────────────────────────────────────────────────────────

def _build_summary_note(
    gate_result: LevelGateResult,
    learning_state: str,
    current_stage: int,
    recurring_deviations: list[str],
) -> str:
    """Build a single-sentence summary for CoachContext injection."""
    parts: list[str] = []

    if learning_state == "improving":
        parts.append("User improving consistently.")
    elif learning_state == "declining":
        parts.append("Readiness declining — system under pressure.")
    elif learning_state == "plateaued":
        parts.append("Readiness has plateaued — check plan relevance.")
    else:
        parts.append("Trajectory stable.")

    if gate_result.ready:
        parts.append(f"Ready for Stage {gate_result.next_stage}.")
    elif not gate_result.floor_met:
        parts.append("Session count below floor.")
    elif not gate_result.gate_1_adherence.passed:
        parts.append("Adherence gate not met.")
    elif not gate_result.gate_2_readiness.passed:
        parts.append("Readiness trend not yet sufficient.")

    if recurring_deviations:
        parts.append(f"Recurring deviations: {', '.join(recurring_deviations)}.")

    if gate_result.suppressed_by:
        parts.append("Advancement suppressed by conversation signal.")

    return " ".join(parts)

def assess_daily_adherence(plan_items: list, llm_client=None) -> list:
    for item in plan_items:
        if item.get("has_evidence"):
            item["adherence_score"] = 1.0
        elif item.get("deviation_reason"):
            item["adherence_score"] = 0.0
        else:
            if llm_client and hasattr(llm_client, "estimate_adherence"):
                item["adherence_score"] = float(llm_client.estimate_adherence(item))
            else:
                item["adherence_score"] = 0.0
    return plan_items
