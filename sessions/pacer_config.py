"""
sessions/pacer_config.py

The ring's timing contract.

The ring (haptic or audio) is unchanged in character across all practices.
Only the timing parameters change. PacerConfig is a pure data object — it
carries exactly the values the device needs to drive the pacer.

Design
------
The four parameters (inhale, pause, exhale, pause) are always computed from:
  1. target_bpm  — the rate the user should breathe at
  2. ratio       — how cycle time is divided across the four phases

For resonance breathing:      inhale=exhale, pauses minimal (e.g. 5:1:5:1)
For box breathing:            equal four-part (e.g. 4:4:4:4)
For step-down:                same 4-part structure, target_bpm decreasing

The attention_anchor is orthogonal — it does not change the timing at all.
It is carried here so the device receives everything it needs in one object.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ── Default inhale:pause:exhale:pause ratios per practice ─────────────────────

# Keys match practice_type strings from practice_registry.py
_DEFAULT_RATIOS: dict[str, tuple[float, float, float, float]] = {
    # (inhale_frac, pause_after_inhale_frac, exhale_frac, pause_after_exhale_frac)
    "ring_entrainment":  (0.45, 0.05, 0.45, 0.05),
    "prf_discovery":     (0.45, 0.05, 0.45, 0.05),
    "resonance_hold":    (0.45, 0.05, 0.45, 0.05),
    "box_breathing":     (0.25, 0.25, 0.25, 0.25),   # equal 4-part
    "plexus_step_down":  (0.45, 0.05, 0.45, 0.05),
    "plexus_hold":       (0.45, 0.05, 0.45, 0.05),
    "silent_meditation": (0.45, 0.05, 0.45, 0.05),   # unused (no pacer)
}


# ── Dataclass ─────────────────────────────────────────────────────────────────

@dataclass
class PacerConfig:
    """
    Complete timing specification for the ring pacer.

    Sent directly to the device/UI layer via the API.

    Fields
    ------
    target_bpm : float
        The target breathing rate the pacer is currently set to.
        For step-down sessions this changes during the session.
    inhale_sec : float
        Duration of the inhale phase in seconds.
    pause_after_inhale_sec : float
        Duration of the pause after inhale.
    exhale_sec : float
        Duration of the exhale phase.
    pause_after_exhale_sec : float
        Duration of the pause after exhale.
    step_down_enabled : bool
        True if target_bpm will decrease during the session.
    step_down_from_bpm : float
        Starting BPM for step-down. Typically detected current BPM or 12.0.
    step_down_to_bpm : float
        Target BPM to stop at. Typically stored PRF or 6.0.
    step_down_increment : float
        BPM drop per step. Default 0.5.
    attention_anchor : str | None
        Body area to direct attention toward. None for pure breathing.
        Valid values: "belly" | "heart" | "solar" | "root" | "brow"
    """
    target_bpm:              float
    inhale_sec:              float
    pause_after_inhale_sec:  float
    exhale_sec:              float
    pause_after_exhale_sec:  float
    step_down_enabled:       bool          = False
    step_down_from_bpm:      float         = 12.0
    step_down_to_bpm:        float         = 6.0
    step_down_increment:     float         = 0.5
    attention_anchor:        Optional[str] = None

    @property
    def cycle_duration_sec(self) -> float:
        """Total duration of one breath cycle in seconds."""
        return (
            self.inhale_sec
            + self.pause_after_inhale_sec
            + self.exhale_sec
            + self.pause_after_exhale_sec
        )

    @property
    def implied_bpm(self) -> float:
        """BPM implied by the current phase durations."""
        if self.cycle_duration_sec > 0:
            return round(60.0 / self.cycle_duration_sec, 3)
        return 0.0

    def stepped_down(self) -> "PacerConfig":
        """
        Return a new PacerConfig with target_bpm reduced by step_down_increment.
        Does not mutate self.
        """
        new_bpm = max(self.step_down_to_bpm, self.target_bpm - self.step_down_increment)
        return build_pacer_config(
            practice_type     = "prf_discovery",  # ratio preserved
            target_bpm        = new_bpm,
            step_down_enabled = self.step_down_enabled,
            step_down_from_bpm= self.step_down_from_bpm,
            step_down_to_bpm  = self.step_down_to_bpm,
            step_down_increment = self.step_down_increment,
            attention_anchor  = self.attention_anchor,
            inhale_frac       = self.inhale_sec / self.cycle_duration_sec,
            pause_inhale_frac = self.pause_after_inhale_sec / self.cycle_duration_sec,
            exhale_frac       = self.exhale_sec / self.cycle_duration_sec,
            pause_exhale_frac = self.pause_after_exhale_sec / self.cycle_duration_sec,
        )

    def at_floor(self) -> bool:
        """True if target_bpm has reached or gone below step_down_to_bpm."""
        return self.target_bpm <= self.step_down_to_bpm


# ── Factory ────────────────────────────────────────────────────────────────────

def build_pacer_config(
    practice_type: str,
    target_bpm: float,
    *,
    step_down_enabled:   bool          = False,
    step_down_from_bpm:  float         = 12.0,
    step_down_to_bpm:    float         = 6.0,
    step_down_increment: float         = 0.5,
    attention_anchor:    Optional[str] = None,
    # Override ratios if needed (fractions, must sum to 1.0)
    inhale_frac:         Optional[float] = None,
    pause_inhale_frac:   Optional[float] = None,
    exhale_frac:         Optional[float] = None,
    pause_exhale_frac:   Optional[float] = None,
) -> PacerConfig:
    """
    Build a PacerConfig for a given practice type and target BPM.

    Parameters
    ----------
    practice_type : str
        Used to look up default phase ratios.
    target_bpm : float
        The rate to pace the user at.
    step_down_* : parameters
        Only relevant when step_down_enabled=True.
    attention_anchor : str | None
        Body area anchor (orthogonal to timing).
    inhale_frac, pause_inhale_frac, exhale_frac, pause_exhale_frac : float | None
        Override the default ratio. All four must be provided together
        if any override is given. Must sum to 1.0.

    Returns
    -------
    PacerConfig
    """
    # Phase ratios
    if all(v is not None for v in [inhale_frac, pause_inhale_frac, exhale_frac, pause_exhale_frac]):
        ratios = (inhale_frac, pause_inhale_frac, exhale_frac, pause_exhale_frac)
    else:
        ratios = _DEFAULT_RATIOS.get(practice_type, _DEFAULT_RATIOS["resonance_hold"])

    cycle_sec = 60.0 / max(target_bpm, 0.5)   # guard against zero

    return PacerConfig(
        target_bpm              = round(target_bpm, 2),
        inhale_sec              = round(ratios[0] * cycle_sec, 3),
        pause_after_inhale_sec  = round(ratios[1] * cycle_sec, 3),
        exhale_sec              = round(ratios[2] * cycle_sec, 3),
        pause_after_exhale_sec  = round(ratios[3] * cycle_sec, 3),
        step_down_enabled       = step_down_enabled,
        step_down_from_bpm      = step_down_from_bpm,
        step_down_to_bpm        = step_down_to_bpm,
        step_down_increment     = step_down_increment,
        attention_anchor        = attention_anchor,
    )
