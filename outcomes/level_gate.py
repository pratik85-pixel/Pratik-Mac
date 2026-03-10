"""
outcomes/level_gate.py

Readiness criteria for advancing from one NS-health stage to the next.

Each stage transition has:
  1. Minimum qualifying sessions (enough history to judge)
  2. A coherence criterion (sustained quality at the right level)
  3. A minimum NS-health total_score from NSHealthProfile
  4. An additional behavioural criterion (rmssd delta trend, arc completion rate, etc.)

None of the gates fire unless all four criteria are met.  partial_met is
surfaced via criteria_met so the coach can give targeted encouragement.

Level gate criteria
-------------------
Stage 0→1 : min_sessions=2,  data_quality_avg≥0.50,    total_score≥35,  stable signal
Stage 1→2 : min_sessions=6,  coherence_avg_last3≥0.40, total_score≥55,  rmssd_delta_positive≥50%
Stage 2→3 : min_sessions=12, coherence_avg_last3≥0.55, total_score≥70,  arc_completed≥50%
Stage 3→4 : min_sessions=18, coherence_peak_avg≥0.70,  total_score≥80,  rmssd_delta_positive≥60%
Stage 4→5 : min_sessions=24, coherence_peak_avg≥0.80,  total_score≥90,  arc_duration shortening
Stage 5   : no advancement possible
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from archetypes.scorer import NSHealthProfile
from outcomes.session_outcomes import (
    SessionOutcome,
    arc_completion_fraction,
    arc_duration_trend,
    coherence_avg_last_n,
    coherence_peak_avg,
    data_quality_avg,
    rmssd_delta_positive_fraction,
)


# ── Output dataclass ──────────────────────────────────────────────────────────

@dataclass
class LevelGateResult:
    """
    Outcome of a level-gate check.

    ``ready``       — True if ALL criteria are met and advancement is possible.
    ``current_stage`` — User's current NS-health stage (0–5).
    ``criteria_met``  — Dict of criterion_name → bool for every required check.
    ``blocking``      — Human-readable plain-English list of unmet criteria.
    ``next_stage``    — Stage that would be reached if ready=True (None if stage=5).
    """
    ready:         bool
    current_stage: int
    criteria_met:  dict[str, bool]
    blocking:      list[str]
    next_stage:    Optional[int] = None


# ── Public API ─────────────────────────────────────────────────────────────────

def check_level_gate(
    profile: NSHealthProfile,
    session_history: list[SessionOutcome],
) -> LevelGateResult:
    """
    Evaluate whether the user is ready to graduate from their current stage.

    Parameters
    ----------
    profile : NSHealthProfile
        Current computed NS-health profile (from archetypes.scorer).
    session_history : list[SessionOutcome]
        All SessionOutcome records for this user in chronological order.

    Returns
    -------
    LevelGateResult
        ready=True only when every criterion for the current→next transition
        is satisfied.  ready=False with an empty blocking list means the user
        is at stage 5 (no further advancement).
    """
    stage = profile.stage

    if stage >= 5:
        return LevelGateResult(
            ready=False,
            current_stage=stage,
            criteria_met={},
            blocking=[],
            next_stage=None,
        )

    gate_fn = _GATE_FUNCTIONS.get(stage)
    if gate_fn is None:
        # Should never happen with stage in 0–4
        return LevelGateResult(
            ready=False,
            current_stage=stage,
            criteria_met={},
            blocking=["unknown_stage"],
        )

    return gate_fn(profile, session_history)


# ── Gate implementations ───────────────────────────────────────────────────────

def _check_gate_0_to_1(
    profile: NSHealthProfile,
    history: list[SessionOutcome],
) -> LevelGateResult:
    """
    Stage 0 → 1: User can produce a stable signal.

    Criteria:
        min_sessions          ≥ 2
        data_quality_avg      ≥ 0.50
        total_score           ≥ 35
    """
    current = 0
    n = len(history)
    dq = data_quality_avg(history)
    score = profile.total_score

    met = {
        "sufficient_sessions":      n >= 2,
        "data_quality_avg_0.50":    dq >= 0.50,
        "total_score_35":           score >= 35,
    }
    blocking = _build_blocking(met, {
        "sufficient_sessions":      f"Need at least 2 qualifying sessions (you have {n})",
        "data_quality_avg_0.50":    f"Signal quality average needs to reach 50% (currently {dq:.0%})",
        "total_score_35":           f"NS health score needs to reach 35 (currently {score})",
    })

    return LevelGateResult(
        ready=all(met.values()),
        current_stage=current,
        criteria_met=met,
        blocking=blocking,
        next_stage=1,
    )


def _check_gate_1_to_2(
    profile: NSHealthProfile,
    history: list[SessionOutcome],
) -> LevelGateResult:
    """
    Stage 1 → 2: Consistent coherence is emerging.

    Criteria:
        min_sessions                ≥ 6
        coherence_avg_last3         ≥ 0.40
        total_score                 ≥ 55
        rmssd_delta_positive_frac   ≥ 50% of sessions
    """
    current = 1
    n = len(history)
    coh_last3 = coherence_avg_last_n(history, 3)
    score = profile.total_score
    delta_pos = rmssd_delta_positive_fraction(history)

    met = {
        "sufficient_sessions":           n >= 6,
        "coherence_avg_last3_0.40":      (coh_last3 or 0.0) >= 0.40,
        "total_score_55":                score >= 55,
        "rmssd_delta_positive_50pct":    delta_pos >= 0.50,
    }
    blocking = _build_blocking(met, {
        "sufficient_sessions":           f"Need at least 6 qualifying sessions (you have {n})",
        "coherence_avg_last3_0.40":      f"Coherence average over last 3 sessions needs to reach 0.40 "
                                          f"(currently {f'{coh_last3:.3f}' if coh_last3 is not None else 'N/A'})",
        "total_score_55":                f"NS health score needs to reach 55 (currently {score})",
        "rmssd_delta_positive_50pct":    f"Heart rate variability needs to improve in at least 50% of sessions "
                                          f"(currently {delta_pos:.0%})",
    })

    return LevelGateResult(
        ready=all(met.values()),
        current_stage=current,
        criteria_met=met,
        blocking=blocking,
        next_stage=2,
    )


def _check_gate_2_to_3(
    profile: NSHealthProfile,
    history: list[SessionOutcome],
) -> LevelGateResult:
    """
    Stage 2 → 3: Recovery arc is reliably forming.

    Criteria:
        min_sessions                ≥ 12
        coherence_avg_last3         ≥ 0.55
        total_score                 ≥ 70
        arc_completion_frac         ≥ 50% of sessions
    """
    current = 2
    n = len(history)
    coh_last3 = coherence_avg_last_n(history, 3)
    score = profile.total_score
    arc_frac = arc_completion_fraction(history)

    met = {
        "sufficient_sessions":       n >= 12,
        "coherence_avg_last3_0.55":  (coh_last3 or 0.0) >= 0.55,
        "total_score_70":            score >= 70,
        "arc_completed_50pct":       arc_frac >= 0.50,
    }
    blocking = _build_blocking(met, {
        "sufficient_sessions":       f"Need at least 12 qualifying sessions (you have {n})",
        "coherence_avg_last3_0.55":  f"Coherence average over last 3 sessions needs to reach 0.55 "
                                      f"(currently {f'{coh_last3:.3f}' if coh_last3 is not None else 'N/A'})",
        "total_score_70":            f"NS health score needs to reach 70 (currently {score})",
        "arc_completed_50pct":       f"A full recovery arc needs to complete in at least 50% of sessions "
                                      f"(currently {arc_frac:.0%})",
    })

    return LevelGateResult(
        ready=all(met.values()),
        current_stage=current,
        criteria_met=met,
        blocking=blocking,
        next_stage=3,
    )


def _check_gate_3_to_4(
    profile: NSHealthProfile,
    history: list[SessionOutcome],
) -> LevelGateResult:
    """
    Stage 3 → 4: Peak coherence is consistently high.

    Criteria:
        min_sessions                ≥ 18
        coherence_peak_avg          ≥ 0.70
        total_score                 ≥ 80
        rmssd_delta_positive_frac   ≥ 60% of sessions
    """
    current = 3
    n = len(history)
    peak_avg = coherence_peak_avg(history)
    score = profile.total_score
    delta_pos = rmssd_delta_positive_fraction(history)

    met = {
        "sufficient_sessions":          n >= 18,
        "coherence_peak_avg_0.70":      (peak_avg or 0.0) >= 0.70,
        "total_score_80":               score >= 80,
        "rmssd_delta_positive_60pct":   delta_pos >= 0.60,
    }
    blocking = _build_blocking(met, {
        "sufficient_sessions":          f"Need at least 18 qualifying sessions (you have {n})",
        "coherence_peak_avg_0.70":      f"Average peak coherence needs to reach 0.70 "
                                         f"(currently {f'{peak_avg:.3f}' if peak_avg is not None else 'N/A'})",
        "total_score_80":               f"NS health score needs to reach 80 (currently {score})",
        "rmssd_delta_positive_60pct":   f"Heart rate variability needs to improve in at least 60% of sessions "
                                         f"(currently {delta_pos:.0%})",
    })

    return LevelGateResult(
        ready=all(met.values()),
        current_stage=current,
        criteria_met=met,
        blocking=blocking,
        next_stage=4,
    )


def _check_gate_4_to_5(
    profile: NSHealthProfile,
    history: list[SessionOutcome],
) -> LevelGateResult:
    """
    Stage 4 → 5: Elite — arc is forming faster and coherence is near ceiling.

    Criteria:
        min_sessions                ≥ 24
        coherence_peak_avg          ≥ 0.80
        total_score                 ≥ 90
        arc_duration_trend          == "shortening"
    """
    current = 4
    n = len(history)
    peak_avg = coherence_peak_avg(history)
    score = profile.total_score
    arc_trend = arc_duration_trend(history, baseline_n=6, recent_n=3)

    met = {
        "sufficient_sessions":       n >= 24,
        "coherence_peak_avg_0.80":   (peak_avg or 0.0) >= 0.80,
        "total_score_90":            score >= 90,
        "arc_duration_shortening":   arc_trend == "shortening",
    }
    blocking = _build_blocking(met, {
        "sufficient_sessions":       f"Need at least 24 qualifying sessions (you have {n})",
        "coherence_peak_avg_0.80":   f"Average peak coherence needs to reach 0.80 "
                                      f"(currently {f'{peak_avg:.3f}' if peak_avg is not None else 'N/A'})",
        "total_score_90":            f"NS health score needs to reach 90 (currently {score})",
        "arc_duration_shortening":   f"Recovery arc duration needs to be shortening compared to your "
                                      f"first 6 sessions (current trend: {arc_trend})",
    })

    return LevelGateResult(
        ready=all(met.values()),
        current_stage=current,
        criteria_met=met,
        blocking=blocking,
        next_stage=5,
    )


# ── Routing table ─────────────────────────────────────────────────────────────

_GATE_FUNCTIONS = {
    0: _check_gate_0_to_1,
    1: _check_gate_1_to_2,
    2: _check_gate_2_to_3,
    3: _check_gate_3_to_4,
    4: _check_gate_4_to_5,
}


# ── Private helpers ────────────────────────────────────────────────────────────

def _build_blocking(
    criteria_met: dict[str, bool],
    messages: dict[str, str],
) -> list[str]:
    """Return plain-English descriptions for every unmet criterion."""
    return [messages[k] for k, v in criteria_met.items() if not v and k in messages]
