"""
coach/milestone_detector.py

Detects physiologically significant milestone events.

Design
------
milestone_detector runs BEFORE context_builder and before tone_selector.
If it fires, tone_selector immediately returns CELEBRATE regardless of other signals.

Detection rules (any one fires a milestone):
    1. Score jump ≥5 in 7 days
    2. Coherence floor crossed a new threshold band
    3. Recovery arc shortened ≥20 minutes vs 2-week average
    4. First dimension score reaching ≥15 (first time)
    5. Stage advancement

Evidence rule: milestone_evidence MUST contain a specific number.
If no number can be produced, milestone is suppressed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from archetypes.scorer import NSHealthProfile
from model.baseline_builder import PersonalFingerprint


# ── Thresholds ────────────────────────────────────────────────────────────────

_SCORE_JUMP_THRESHOLD       = 5      # points in 7 days
_ARC_IMPROVEMENT_MINUTES    = 20     # minutes shorter vs 2-week average
_HIGH_DIMENSION_THRESHOLD   = 15     # out of 20
_COHERENCE_THRESHOLDS       = (0.10, 0.20, 0.30, 0.40, 0.60)  # floor crossing bands


# ── Milestone dataclass ───────────────────────────────────────────────────────

@dataclass
class Milestone:
    """
    A detected milestone event.

    label    — short human label injected into CoachContext.milestone
    evidence — specific number-containing statement injected into CoachContext.milestone_evidence
    kind     — internal tag for analytics
    """
    label:    str
    evidence: str   # always contains at least one digit
    kind:     str   # "score_jump"|"arc_improvement"|"coherence_band"|"dimension_peak"|"stage_advance"


# ── Public API ────────────────────────────────────────────────────────────────

def detect_milestone(
    profile: NSHealthProfile,
    fingerprint: PersonalFingerprint,
    *,
    previous_stage: Optional[int] = None,
    previous_score: Optional[int] = None,
    previous_arc_mean_hours: Optional[float] = None,
    previous_coherence_floor: Optional[float] = None,
    previous_dimension_scores: Optional[dict] = None,
) -> Optional[Milestone]:
    """
    Detect the most significant milestone from the current profile snapshot.

    Returns the FIRST match in priority order, or None.

    Parameters
    ----------
    profile : NSHealthProfile
        Current scoring output.
    fingerprint : PersonalFingerprint
        Current personal baseline.
    previous_stage : int | None
        Stage at last check — used for stage advancement detection.
    previous_score : int | None
        Total score at last check (7 days ago).
    previous_arc_mean_hours : float | None
        Recovery arc mean 2 weeks ago, in hours.
    previous_coherence_floor : float | None
        Coherence floor reading from prior snapshot.
    previous_dimension_scores : dict | None
        Dict of previous dimension scores — keys matching profile.dimension_breakdown().

    Returns
    -------
    Milestone | None
    """
    # 1. Stage advancement (highest priority)
    if previous_stage is not None and profile.stage > previous_stage:
        return Milestone(
            label    = f"stage advance to Stage {profile.stage}",
            evidence = f"total score reached {profile.total_score} — Stage {profile.stage} threshold crossed",
            kind     = "stage_advance",
        )

    # 2. Score jump ≥5 in 7 days
    if previous_score is not None:
        delta = profile.total_score - previous_score
        if delta >= _SCORE_JUMP_THRESHOLD:
            return Milestone(
                label    = f"+{delta} point jump this week",
                evidence = (
                    f"score moved from {previous_score} to {profile.total_score} "
                    f"({delta} points in 7 days)"
                ),
                kind     = "score_jump",
            )

    # 3. Recovery arc shortened ≥20 minutes
    if (
        fingerprint.recovery_arc_mean_hours is not None
        and previous_arc_mean_hours is not None
    ):
        delta_minutes = (previous_arc_mean_hours - fingerprint.recovery_arc_mean_hours) * 60
        if delta_minutes >= _ARC_IMPROVEMENT_MINUTES:
            new_hrs = fingerprint.recovery_arc_mean_hours
            old_hrs = previous_arc_mean_hours
            return Milestone(
                label    = f"{int(delta_minutes)} minute recovery improvement",
                evidence = (
                    f"recovery arc now averaging {new_hrs:.1f}hrs "
                    f"vs {old_hrs:.1f}hrs two weeks ago "
                    f"— {int(delta_minutes)} minutes faster"
                ),
                kind     = "arc_improvement",
            )

    # 4. Coherence floor crossed a new band
    if (
        fingerprint.coherence_floor is not None
        and previous_coherence_floor is not None
    ):
        for band in _COHERENCE_THRESHOLDS:
            if previous_coherence_floor < band <= fingerprint.coherence_floor:
                return Milestone(
                    label    = f"coherence floor crossed {band:.2f}",
                    evidence = (
                        f"resting coherence floor reached {fingerprint.coherence_floor:.2f} "
                        f"— past the {band:.2f} threshold"
                    ),
                    kind     = "coherence_band",
                )

    # 5. First dimension reaching ≥15
    if previous_dimension_scores is not None:
        dims = profile.dimension_breakdown()
        for dim_name, current_val in dims.items():
            prev_val = previous_dimension_scores.get(dim_name, 0)
            if prev_val < _HIGH_DIMENSION_THRESHOLD <= current_val:
                return Milestone(
                    label    = f"{dim_name.replace('_', ' ')} reached {current_val}/20",
                    evidence = (
                        f"{dim_name.replace('_', ' ')} score reached {current_val} out of 20 "
                        f"— up from {prev_val}"
                    ),
                    kind     = "dimension_peak",
                )

    return None
