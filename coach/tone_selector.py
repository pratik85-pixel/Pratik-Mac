"""
coach/tone_selector.py

Deterministic tone selection — runs BEFORE context assembly and BEFORE the LLM call.

Design:
    The LLM is not asked to infer tone from physiological data.
    Tone is selected by Python and injected as a hard constraint.

    A user going through a hard week cannot accidentally receive a PUSH message
    because the LLM decided they "sounded resilient". The tone is pre-decided.

Four tones:
    CELEBRATE  — milestone or significant positive delta (overrides all)
    WARN       — active overload signal (overrides PUSH)
    COMPASSION — declining + stressor compounding
    PUSH       — improving + capacity present + no warn/celebrate condition

Selection runs in priority order: CELEBRATE > WARN > COMPASSION > PUSH.
PUSH is the default — it is only applied when the higher tones don't fire.
"""

from __future__ import annotations

from typing import Optional

from archetypes.scorer import NSHealthProfile


# ── Constants ──────────────────────────────────────────────────────────────────

TONE_CELEBRATE  = "CELEBRATE"
TONE_WARN       = "WARN"
TONE_COMPASSION = "COMPASSION"
TONE_PUSH       = "PUSH"

# Thresholds — calibrated against PersonalFingerprint relative signals
_WARN_LF_HF_THRESHOLD      = 2.8    # lf_hf_resting above this + trending → WARN
_WARN_CONSECUTIVE_LOWS     = 2      # this many below-floor reads → WARN
_COMPASSION_DELTA_THRESHOLD = -3    # 7d score delta this bad → COMPASSION eligible
_CELEBRATE_DELTA_THRESHOLD  = 5     # 7d score delta this good (if no milestone) → CELEBRATE


# ── Public API ─────────────────────────────────────────────────────────────────

def select_tone(
    profile: NSHealthProfile,
    *,
    milestone_detected: bool = False,
    consecutive_low_reads: int = 0,
    external_stressor_flagged: bool = False,
    lf_hf_resting: Optional[float] = None,
    lf_hf_trending_up: bool = False,
    morning_rmssd_vs_floor: Optional[float] = None,
) -> str:
    """
    Select coaching tone for the current message.

    Parameters
    ----------
    profile : NSHealthProfile
        Current scoring profile.
    milestone_detected : bool
        True if milestone_detector has fired a significant change event.
    consecutive_low_reads : int
        Number of consecutive below-floor morning reads.
    external_stressor_flagged : bool
        True if conversation extractor or onboarding flagged an external stressor.
    lf_hf_resting : float | None
        Current resting sympathovagal ratio from PersonalFingerprint.
    lf_hf_trending_up : bool
        True if lf_hf_resting has been rising over the last 7 days.
    morning_rmssd_vs_floor : float | None
        Fractional delta vs personal floor. Negative = below floor.

    Returns
    -------
    str
        One of: "CELEBRATE" | "WARN" | "COMPASSION" | "PUSH"
    """
    # ── CELEBRATE (overrides everything) ─────────────────────────────────────
    if milestone_detected:
        return TONE_CELEBRATE

    if profile.score_7d_delta is not None and profile.score_7d_delta >= _CELEBRATE_DELTA_THRESHOLD:
        return TONE_CELEBRATE

    # ── WARN (overrides PUSH) ─────────────────────────────────────────────────
    if _is_warn(
        profile               = profile,
        consecutive_low_reads = consecutive_low_reads,
        lf_hf_resting         = lf_hf_resting,
        lf_hf_trending_up     = lf_hf_trending_up,
        morning_rmssd_vs_floor= morning_rmssd_vs_floor,
    ):
        return TONE_WARN

    # ── COMPASSION ────────────────────────────────────────────────────────────
    if _is_compassion(
        profile                   = profile,
        consecutive_low_reads     = consecutive_low_reads,
        external_stressor_flagged = external_stressor_flagged,
        morning_rmssd_vs_floor    = morning_rmssd_vs_floor,
    ):
        return TONE_COMPASSION

    # ── PUSH (default) ────────────────────────────────────────────────────────
    return TONE_PUSH


# ── Tone evaluation helpers ────────────────────────────────────────────────────

def _is_warn(
    profile: NSHealthProfile,
    consecutive_low_reads: int,
    lf_hf_resting: Optional[float],
    lf_hf_trending_up: bool,
    morning_rmssd_vs_floor: Optional[float],
) -> bool:
    """
    WARN fires on active physiological overload signals.

    Conditions (any one sufficient):
    1. 2+ consecutive below-floor morning reads
    2. LF/HF resting > 2.8 AND trending upward
    3. Morning read > 20% below personal floor (severe depletion)
    """
    if consecutive_low_reads >= _WARN_CONSECUTIVE_LOWS:
        return True

    if (
        lf_hf_resting is not None
        and lf_hf_resting > _WARN_LF_HF_THRESHOLD
        and lf_hf_trending_up
    ):
        return True

    if morning_rmssd_vs_floor is not None and morning_rmssd_vs_floor < -0.20:
        return True

    return False


def _is_compassion(
    profile: NSHealthProfile,
    consecutive_low_reads: int,
    external_stressor_flagged: bool,
    morning_rmssd_vs_floor: Optional[float],
) -> bool:
    """
    COMPASSION fires when score is declining AND at least one compounding factor is present.

    Declining alone is not enough — a stable-but-hard day gets PUSH.
    Compounding factor alone (external stress, one low read) is not enough — needs the decline.
    """
    score_declining = (
        profile.trajectory == "declining"
        or (profile.score_7d_delta is not None and profile.score_7d_delta <= _COMPASSION_DELTA_THRESHOLD)
    )

    if not score_declining:
        return False

    # At least one compounding factor needed
    if consecutive_low_reads >= 1:
        return True
    if external_stressor_flagged:
        return True
    if morning_rmssd_vs_floor is not None and morning_rmssd_vs_floor < -0.10:
        return True

    return False


# ── Tone descriptions (for context injection) ─────────────────────────────────

TONE_DESCRIPTIONS: dict[str, str] = {
    TONE_CELEBRATE: (
        "The user has made a meaningful physiological change. "
        "Acknowledge the specific evidence. Be warm but specific — reference the number."
    ),
    TONE_WARN: (
        "The body is showing active overload signals. "
        "Be direct but not alarming. One clear action. No minimising."
    ),
    TONE_COMPASSION: (
        "The user is under pressure and the physiology confirms it. "
        "Acknowledge what the body is doing. Do not push. Do not minimise. "
        "Give the minimum effective dose."
    ),
    TONE_PUSH: (
        "The body has capacity. The trajectory is positive. "
        "Reinforce the progress. Give the full stage-appropriate action. "
        "Be direct — not cheerleader-ish."
    ),
}
