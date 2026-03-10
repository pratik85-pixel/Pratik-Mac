"""
sessions/session_schema.py

PracticeSession — the complete device-ready session contract.

This is the object the API sends to the device/UI after the prescriber has
decided what to do. It carries everything the device needs:
  - Which practice to run
  - How to configure the ring pacer (or that there is no pacer)
  - How long to run
  - Plain-English instructions for the UI

Design note
-----------
PracticeSession is a data-only object. No computation happens here. All
decisions are made upstream in session_prescriber.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sessions.pacer_config import PacerConfig


@dataclass
class PracticeSession:
    """
    Complete device-ready session specification.

    Sent from the API to the UI/device layer.

    Fields
    ------
    practice_type : str
        Canonical practice identifier. See practice_registry.py.
    pacer : PacerConfig | None
        Ring timing config. None for silent_meditation.
    attention_anchor : str | None
        Body area to direct attention toward. None for non-plexus practices.
        Valid: "belly" | "heart" | "solar" | "root" | "brow"
    duration_minutes : int
        Prescribed session length.
    gates_required : bool
        True for prf_discovery and plexus_step_down — device must evaluate
        gates and report step-down events back to the backend.
    prf_target_bpm : float | None
        When gates_required=True, the BPM at which to stop stepping down.
        None when PRF is unknown (step down until Gate C fires).
    session_notes : list[str]
        Plain-English instructions shown to the user in the UI.
    tier : int
        1 | 2 | 3 — practice tier, for UI grouping.
    """
    practice_type:    str
    pacer:            Optional[PacerConfig]
    attention_anchor: Optional[str]
    duration_minutes: int
    gates_required:   bool
    prf_target_bpm:   Optional[float]
    session_notes:    list[str] = field(default_factory=list)
    tier:             int = 1

    def has_pacer(self) -> bool:
        """True if the device should run the ring pacer for this session."""
        return self.pacer is not None

    def is_step_down(self) -> bool:
        """True if this session uses dynamic step-down BPM logic."""
        return self.pacer is not None and self.pacer.step_down_enabled

    def to_dict(self) -> dict:
        """
        Serialise to a plain dict for JSON delivery via the API.
        All optional fields are included (None values included explicitly).
        """
        pacer_dict = None
        if self.pacer is not None:
            pacer_dict = {
                "target_bpm":              self.pacer.target_bpm,
                "inhale_sec":              self.pacer.inhale_sec,
                "pause_after_inhale_sec":  self.pacer.pause_after_inhale_sec,
                "exhale_sec":              self.pacer.exhale_sec,
                "pause_after_exhale_sec":  self.pacer.pause_after_exhale_sec,
                "step_down_enabled":       self.pacer.step_down_enabled,
                "step_down_from_bpm":      self.pacer.step_down_from_bpm,
                "step_down_to_bpm":        self.pacer.step_down_to_bpm,
                "step_down_increment":     self.pacer.step_down_increment,
                "attention_anchor":        self.pacer.attention_anchor,
            }

        return {
            "practice_type":    self.practice_type,
            "pacer":            pacer_dict,
            "attention_anchor": self.attention_anchor,
            "duration_minutes": self.duration_minutes,
            "gates_required":   self.gates_required,
            "prf_target_bpm":   self.prf_target_bpm,
            "session_notes":    self.session_notes,
            "tier":             self.tier,
        }
