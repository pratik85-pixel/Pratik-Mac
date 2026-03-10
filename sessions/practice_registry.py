"""
sessions/practice_registry.py

Canonical list of all prescribable practices with their stage gates,
pacer requirements, and human-readable descriptions.

This is the single source of truth for:
  - What practice_type strings are valid
  - What stage a practice becomes available
  - Whether a practice requires step-down gates
  - Whether a practice requires a stored PRF

Nothing outside this module should hardcode practice names.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ── Practice descriptor ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PracticeDescriptor:
    """
    Static definition of one practice type.

    Fields
    ------
    practice_type : str
        Canonical identifier. Used in DailyPrescription, PracticeSession,
        SessionOutcome, and all API/DB payloads.
    label : str
        Short human-readable name.
    description : str
        One-sentence description shown to the user.
    min_stage : int
        Practice is not prescribed below this stage.
    max_stage : int
        Practice is not prescribed above this stage (5 = no ceiling).
    requires_prf : bool
        True if a stored PRF is required before this practice can run.
    step_down : bool
        True if the session uses step-down BPM logic.
    pacer_required : bool
        False only for silent_meditation (no ring timing).
    attention_anchor_allowed : bool
        True if an attention_anchor can be attached.
    prescribed_on_high_stress : bool
        True if this practice is specifically for acute stress states.
    tier : int
        1 = foundation, 2 = technique expansion, 3 = internalization.
    """
    practice_type:              str
    label:                      str
    description:                str
    min_stage:                  int
    max_stage:                  int
    requires_prf:               bool
    step_down:                  bool
    pacer_required:             bool
    attention_anchor_allowed:   bool
    prescribed_on_high_stress:  bool
    tier:                       int


# ── Registry ───────────────────────────────────────────────────────────────────

_PRACTICES: list[PracticeDescriptor] = [

    # ── Tier 1: Signal establishment ─────────────────────────────────────────

    PracticeDescriptor(
        practice_type             = "ring_entrainment",
        label                     = "Ring Entrainment",
        description               = "Follow the ring at your natural breathing pace. "
                                    "No target — just sync.",
        min_stage                 = 0,
        max_stage                 = 0,
        requires_prf              = False,
        step_down                 = False,
        pacer_required            = True,
        attention_anchor_allowed  = False,
        prescribed_on_high_stress = False,
        tier                      = 1,
    ),

    PracticeDescriptor(
        practice_type             = "prf_discovery",
        label                     = "PRF Discovery",
        description               = "Breathing rate steps down gradually. "
                                    "Your personal resonance frequency is found when coherence peaks.",
        min_stage                 = 0,
        max_stage                 = 1,
        requires_prf              = False,
        step_down                 = True,
        pacer_required            = True,
        attention_anchor_allowed  = False,
        prescribed_on_high_stress = False,
        tier                      = 1,
    ),

    PracticeDescriptor(
        practice_type             = "resonance_hold",
        label                     = "Resonance Hold",
        description               = "Breathe at your personal resonance frequency. "
                                    "The core daily practice.",
        min_stage                 = 1,
        max_stage                 = 5,
        requires_prf              = True,
        step_down                 = False,
        pacer_required            = True,
        attention_anchor_allowed  = False,
        prescribed_on_high_stress = False,
        tier                      = 1,
    ),

    # ── Tier 2: Technique expansion ───────────────────────────────────────────

    PracticeDescriptor(
        practice_type             = "box_breathing",
        label                     = "Box Breathing",
        description               = "Equal inhale-pause-exhale-pause. "
                                    "Prescribed for acute stress states.",
        min_stage                 = 1,
        max_stage                 = 5,
        requires_prf              = False,
        step_down                 = False,
        pacer_required            = True,
        attention_anchor_allowed  = False,
        prescribed_on_high_stress = True,
        tier                      = 2,
    ),

    PracticeDescriptor(
        practice_type             = "plexus_step_down",
        label                     = "Plexus Step-Down",
        description               = "Breathing rate steps down while you direct attention "
                                    "to a specific body area.",
        min_stage                 = 2,
        max_stage                 = 3,
        requires_prf              = False,
        step_down                 = True,
        pacer_required            = True,
        attention_anchor_allowed  = True,
        prescribed_on_high_stress = False,
        tier                      = 2,
    ),

    PracticeDescriptor(
        practice_type             = "plexus_hold",
        label                     = "Plexus Hold",
        description               = "Breathe at your resonance frequency while directing "
                                    "attention to a specific body area.",
        min_stage                 = 2,
        max_stage                 = 4,
        requires_prf              = True,
        step_down                 = False,
        pacer_required            = True,
        attention_anchor_allowed  = True,
        prescribed_on_high_stress = False,
        tier                      = 2,
    ),

    # ── Tier 3: Internalization ───────────────────────────────────────────────

    PracticeDescriptor(
        practice_type             = "silent_meditation",
        label                     = "Silent Meditation",
        description               = "No ring guidance. System records whether coherence "
                                    "at your resonance frequency emerges without cueing.",
        min_stage                 = 4,
        max_stage                 = 5,
        requires_prf              = True,
        step_down                 = False,
        pacer_required            = False,
        attention_anchor_allowed  = False,
        prescribed_on_high_stress = False,
        tier                      = 3,
    ),
]

# Build lookup dict
_REGISTRY: dict[str, PracticeDescriptor] = {p.practice_type: p for p in _PRACTICES}

# Valid practice type strings — used for validation in API layer
VALID_PRACTICE_TYPES: frozenset[str] = frozenset(_REGISTRY.keys())

# Valid attention anchors — orthogonal to practice type
VALID_ATTENTION_ANCHORS: frozenset[str] = frozenset({
    "belly", "heart", "solar", "root", "brow",
})


# ── Public API ─────────────────────────────────────────────────────────────────

def get_practice(practice_type: str) -> PracticeDescriptor:
    """
    Return the PracticeDescriptor for the given practice_type.

    Raises
    ------
    KeyError if practice_type is not in the registry.
    """
    if practice_type not in _REGISTRY:
        raise KeyError(
            f"Unknown practice_type: '{practice_type}'. "
            f"Valid values: {sorted(VALID_PRACTICE_TYPES)}"
        )
    return _REGISTRY[practice_type]


def practices_for_stage(stage: int) -> list[PracticeDescriptor]:
    """Return all practices available at the given stage (min_stage ≤ stage ≤ max_stage)."""
    return [p for p in _PRACTICES if p.min_stage <= stage <= p.max_stage]


def is_available_at_stage(practice_type: str, stage: int) -> bool:
    """True if practice_type is stage-gated as available at the given stage."""
    try:
        p = get_practice(practice_type)
        return p.min_stage <= stage <= p.max_stage
    except KeyError:
        return False
