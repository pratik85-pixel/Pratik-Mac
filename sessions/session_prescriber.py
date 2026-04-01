"""
sessions/session_prescriber.py

Maps (stage, prf_status, load_signal, session_count) → PracticeSession.

This is the single function that decision-making flows through:
  1. Stage gate — is this practice available at this stage?
  2. PRF status — do we need discovery or can we use the stored value?
  3. Load signal — is acute stress overriding the base prescription?
  4. Session count — is this still the entrainment phase (Stage 0)?

Design rule: this module only imports from sessions/ and processing/.
It does NOT import from coach/, archetypes/, or outcomes/.
The coach calls this module — not the other way around.

PRF status strings
------------------
"unknown"   — never run a step-down session. PRF not in fingerprint.
"found"     — PRF found in at least one session but fewer than 3 confirmations.
"confirmed" — PRF confirmed in 3+ sessions. Reliable.
"""

from __future__ import annotations

from typing import Optional

from sessions.pacer_config import PacerConfig, build_pacer_config
from sessions.practice_registry import get_practice, is_available_at_stage
from sessions.session_schema import PracticeSession


# ── PRF status constants ───────────────────────────────────────────────────────
PRF_UNKNOWN   = "unknown"
PRF_FOUND     = "found"
PRF_CONFIRMED = "confirmed"

# How many sessions at Stage 0 use ring_entrainment before switching to prf_discovery
_ENTRAINMENT_SESSION_COUNT = 2

# Composite readiness below which box_breathing overrides (inverse of old load_score)
_LOW_READINESS_THRESHOLD = 35.0   # ~ old load_score >= 0.65
_MODERATE_READINESS_THRESHOLD = 60.0  # ~ old load_score >= 0.40

# Default starting BPM for step-down when current BPM unknown
_DEFAULT_STEP_DOWN_START_BPM = 12.0

# Default target BPM for step-down when PRF unknown
_DEFAULT_STEP_DOWN_STOP_BPM  = 6.0


# ── Public API ─────────────────────────────────────────────────────────────────

def prescribe_session(
    stage: int,
    prf_status: str,
    *,
    session_type: str               = "full",
    readiness_score: float          = 100.0,
    total_sessions_completed: int   = 0,
    stored_prf_bpm: Optional[float] = None,
    detected_current_bpm: Optional[float] = None,
    attention_anchor: Optional[str] = None,
    duration_minutes: Optional[int] = None,
) -> PracticeSession:
    """
    Prescribe a PracticeSession from current state.

    Parameters
    ----------
    stage : int
        User's current NS-health stage (0–5).
    prf_status : str
        "unknown" | "found" | "confirmed"
    session_type : str
        Load label from DailyPrescription. "rest" short-circuits to a
        5-minute resonance hold (or entrainment if no PRF).
    readiness_score : float
        0–100 composite (higher = more capacity). Below ~35 triggers box_breathing (Stage 1+).
    total_sessions_completed : int
        All-time sessions completed. Used to gate ring_entrainment vs prf_discovery.
    stored_prf_bpm : float | None
        PRF from PersonalFingerprint. Required for resonance/plexus practices.
    detected_current_bpm : float | None
        Estimated BPM from breath_rate_estimator. Used as step-down start.
    attention_anchor : str | None
        Body area anchor for plexus practices.
    duration_minutes : int | None
        Override duration. If None, default per-stage duration is used.

    Returns
    -------
    PracticeSession
    """
    # ── Rest prescription — short resonance hold ──────────────────────────────
    if session_type == "rest":
        return _make_rest_session(stage, stored_prf_bpm, duration_minutes)

    # ── High acute stress override — box_breathing ────────────────────────────
    if readiness_score < _LOW_READINESS_THRESHOLD and stage >= 1:
        return _make_box_session(stage, duration_minutes)

    # ── Stage 0: entrainment → PRF discovery ──────────────────────────────────
    if stage == 0:
        if total_sessions_completed < _ENTRAINMENT_SESSION_COUNT:
            return _make_entrainment_session(detected_current_bpm, duration_minutes)
        else:
            return _make_prf_discovery_session(
                detected_current_bpm, stored_prf_bpm, duration_minutes,
                attention_anchor=None,
            )

    # ── PRF still unknown at Stage 1+ — continue discovery ───────────────────
    if prf_status == PRF_UNKNOWN:
        return _make_prf_discovery_session(
            detected_current_bpm, stored_prf_bpm, duration_minutes,
            attention_anchor=None,
        )

    # ── Stage 1: resonance hold (PRF found or confirmed) ─────────────────────
    if stage == 1:
        return _make_resonance_session(stored_prf_bpm, stage, duration_minutes)

    # ── Stage 2–3: plexus practices ───────────────────────────────────────────
    if 2 <= stage <= 3:
        # Re-calibrate PRF if still only "found" (not confirmed)
        if prf_status == PRF_FOUND:
            return _make_prf_discovery_session(
                detected_current_bpm, stored_prf_bpm, duration_minutes,
                attention_anchor=attention_anchor,
            )
        # Confirmed PRF → plexus hold
        return _make_plexus_hold_session(stored_prf_bpm, stage, attention_anchor, duration_minutes)

    # ── Stage 4–5: silent meditation (fallback to resonance under load) ───────
    if stage >= 4:
        if readiness_score < _MODERATE_READINESS_THRESHOLD:
            # Any meaningful load → resonance hold, not silent meditation
            return _make_resonance_session(stored_prf_bpm, stage, duration_minutes)
        return _make_silent_meditation_session(stage, stored_prf_bpm, duration_minutes)

    # Fallback — should never reach here
    return _make_resonance_session(stored_prf_bpm, stage, duration_minutes)


# ── Practice builders ──────────────────────────────────────────────────────────

def _make_entrainment_session(
    detected_bpm: Optional[float],
    duration_override: Optional[int],
) -> PracticeSession:
    start_bpm = detected_bpm or 10.0
    pacer = build_pacer_config(
        practice_type     = "ring_entrainment",
        target_bpm        = start_bpm,
        step_down_enabled = False,
    )
    return PracticeSession(
        practice_type    = "ring_entrainment",
        pacer            = pacer,
        attention_anchor = None,
        duration_minutes = duration_override or 5,
        gates_required   = False,
        prf_target_bpm   = None,
        session_notes    = [
            "Follow the ring at its current pace.",
            "No target breathing rate — just sync your breath to the cue.",
            "This is your warm-up to the practice. No pressure.",
        ],
        tier = 1,
    )


def _make_prf_discovery_session(
    detected_bpm: Optional[float],
    stored_prf_bpm: Optional[float],
    duration_override: Optional[int],
    *,
    attention_anchor: Optional[str],
) -> PracticeSession:
    start_bpm = detected_bpm or _DEFAULT_STEP_DOWN_START_BPM
    stop_bpm  = stored_prf_bpm or _DEFAULT_STEP_DOWN_STOP_BPM
    # Don't step below an already-found PRF
    stop_bpm  = max(stop_bpm, 5.5)

    practice = "plexus_step_down" if attention_anchor else "prf_discovery"
    pacer = build_pacer_config(
        practice_type      = practice,
        target_bpm         = start_bpm,
        step_down_enabled  = True,
        step_down_from_bpm = start_bpm,
        step_down_to_bpm   = stop_bpm,
        step_down_increment= 0.5,
        attention_anchor   = attention_anchor,
    )

    notes = [
        "The ring will slow down gradually.",
        "Match your breathing to the pace — don't force it.",
        "Your resonance frequency is found when the system detects peak coherence.",
    ]
    if attention_anchor:
        notes.append(f"Direct your attention to your {attention_anchor} area as you breathe.")

    return PracticeSession(
        practice_type    = practice,
        pacer            = pacer,
        attention_anchor = attention_anchor,
        duration_minutes = duration_override or 15,
        gates_required   = True,
        prf_target_bpm   = stored_prf_bpm,  # None when completely unknown
        session_notes    = notes,
        tier             = 1 if not attention_anchor else 2,
    )


def _make_resonance_session(
    stored_prf_bpm: Optional[float],
    stage: int,
    duration_override: Optional[int],
) -> PracticeSession:
    target = stored_prf_bpm or 6.0
    pacer = build_pacer_config(
        practice_type     = "resonance_hold",
        target_bpm        = target,
        step_down_enabled = False,
    )
    duration = duration_override or _stage_duration(stage)
    return PracticeSession(
        practice_type    = "resonance_hold",
        pacer            = pacer,
        attention_anchor = None,
        duration_minutes = duration,
        gates_required   = False,
        prf_target_bpm   = target,
        session_notes    = [
            f"Breathe at {target:.1f} breaths per minute.",
            "Follow the ring. Steady and relaxed.",
        ],
        tier = 1,
    )


def _make_box_session(
    stage: int,
    duration_override: Optional[int],
) -> PracticeSession:
    # Box breathing: inhale 4s, hold 4s, exhale 4s, hold 4s = 15 BPM cycle
    # But we express it as BPM: 60 / (4×4) = 3.75 BPM → use 4.0 secper quarter
    box_bpm  = 60.0 / 16.0   # 3.75 BPM at 4:4:4:4
    pacer = build_pacer_config(
        practice_type     = "box_breathing",
        target_bpm        = box_bpm,
        inhale_frac       = 0.25,
        pause_inhale_frac = 0.25,
        exhale_frac       = 0.25,
        pause_exhale_frac = 0.25,
    )
    return PracticeSession(
        practice_type    = "box_breathing",
        pacer            = pacer,
        attention_anchor = None,
        duration_minutes = duration_override or 5,
        gates_required   = False,
        prf_target_bpm   = None,
        session_notes    = [
            "Inhale for 4 counts, hold for 4, exhale for 4, hold for 4.",
            "This is a stress-reset practice — slow and controlled.",
            "Follow the ring's four-part cycle.",
        ],
        tier = 2,
    )


def _make_plexus_hold_session(
    stored_prf_bpm: Optional[float],
    stage: int,
    attention_anchor: Optional[str],
    duration_override: Optional[int],
) -> PracticeSession:
    target = stored_prf_bpm or 6.0
    anchor = attention_anchor or "belly"
    pacer = build_pacer_config(
        practice_type     = "plexus_hold",
        target_bpm        = target,
        attention_anchor  = anchor,
    )
    duration = duration_override or _stage_duration(stage)
    return PracticeSession(
        practice_type    = "plexus_hold",
        pacer            = pacer,
        attention_anchor = anchor,
        duration_minutes = duration,
        gates_required   = False,
        prf_target_bpm   = target,
        session_notes    = [
            f"Breathe at {target:.1f} breaths per minute.",
            f"Direct your attention to your {anchor} area as you inhale and exhale.",
            "Visualise the breath moving in and out of that area.",
        ],
        tier = 2,
    )


def _make_silent_meditation_session(
    stage: int,
    stored_prf_bpm: Optional[float],
    duration_override: Optional[int],
) -> PracticeSession:
    duration = duration_override or _stage_duration(stage)
    return PracticeSession(
        practice_type    = "silent_meditation",
        pacer            = None,
        attention_anchor = None,
        duration_minutes = duration,
        gates_required   = False,
        prf_target_bpm   = stored_prf_bpm,
        session_notes    = [
            "No guided pace today. Sit quietly.",
            "Breathe naturally. The system will record your coherence.",
            "No effort — just presence.",
        ],
        tier = 3,
    )


def _make_rest_session(
    stage: int,
    stored_prf_bpm: Optional[float],
    duration_override: Optional[int],
) -> PracticeSession:
    """Shortest meaningful session — 5-minute resonance hold or entrainment."""
    if stored_prf_bpm:
        return _make_resonance_session(stored_prf_bpm, stage, duration_override or 5)
    return _make_entrainment_session(None, duration_override or 5)


# ── Stage duration defaults ────────────────────────────────────────────────────

def _stage_duration(stage: int) -> int:
    return {0: 5, 1: 10, 2: 15, 3: 20, 4: 25, 5: 30}.get(stage, 10)
