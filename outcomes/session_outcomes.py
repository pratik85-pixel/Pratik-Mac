"""
outcomes/session_outcomes.py

Compute per-session outcomes from a completed guided session.

Design
------
This module is purely computational — it takes what was recorded during a session
and produces a structured result. It does NOT mutate the PersonalFingerprint.
Write-back to the personal model is handled by api/services/model_service.py on
a scheduled basis, reading all stored SessionOutcomes.

Session score formula (composite 0.0–1.0):
    session_score = (coherence_avg × 0.40) + (coherence_peak × 0.30) + (time_in_zone_3_plus × 0.30)

    coherence_avg        — breadth (sustained quality across session)
    coherence_peak       — ceiling (how high did the system get)
    time_in_zone_3_plus  — fraction of windows in zone 3 or 4 (0.60–1.0 coherence)

Pre/post RMSSD delta:
    pre_rmssd_ms  = last 2 minutes of signal before guided breathing begins
    post_rmssd_ms = last 2 minutes of the session
    morning_rmssd_ms stored as context only — not used in delta computation

Recovery arc:
    A "completed arc" = coherence starts ≤ 0.45, rises ≥ 0.15 above start,
    and that elevated state is sustained for ≥ 2 consecutive windows.
    arc_duration_hours = time from first window to when the arc peaked.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import numpy as np

from processing.coherence_scorer import CoherenceResult
from processing.ppi_processor import PPIMetrics


# ── Constants ──────────────────────────────────────────────────────────────────

# Arc detection thresholds
_ARC_START_CEILING    = 0.45   # coherence must start at or below this
_ARC_RISE_MINIMUM     = 0.15   # must rise at least this much above start
_ARC_SUSTAIN_WINDOWS  = 2      # must hold elevated state for this many consecutive windows

# Zone 3+ threshold (from config — mirrored here as constant for testability)
_ZONE_3_MIN_COHERENCE = 0.60   # matches config/scoring.py ZONE_3_MIN

# Session score weights
_W_COHERENCE_AVG  = 0.40
_W_COHERENCE_PEAK = 0.30
_W_ZONE_3_PLUS    = 0.30


# ── Output dataclass ──────────────────────────────────────────────────────────

@dataclass
class SessionOutcome:
    """
    Complete outcome record for one guided session.

    All fields that depend on data quality may be None if insufficient
    windows were valid.
    """

    # ── Identity ──────────────────────────────────────────────────────────────
    session_id:       str
    session_date:     date
    duration_minutes: int
    session_type:     str        # "breathing_only"|"full"|"active_recovery"|"rest"

    # ── Coherence quality ─────────────────────────────────────────────────────
    coherence_avg:        Optional[float]   # mean across valid windows (0.0–1.0)
    coherence_peak:       Optional[float]   # highest single window
    time_in_zone_3_plus:  Optional[float]   # fraction of windows in zone 3 or 4
    session_score:        Optional[float]   # composite 0.0–1.0

    # ── Pre/post RMSSD ────────────────────────────────────────────────────────
    pre_rmssd_ms:    Optional[float]   # last 2-min window before guided breathing
    post_rmssd_ms:   Optional[float]   # last 2-min window of session
    rmssd_delta_ms:  Optional[float]   # post − pre (positive = improved during session)
    rmssd_delta_pct: Optional[float]   # delta relative to pre_rmssd_ms

    # ── Recovery arc ──────────────────────────────────────────────────────────
    arc_completed:       bool
    arc_duration_hours:  Optional[float]   # time from first window to arc peak

    # ── Context (stored but not used in score computation) ────────────────────
    morning_rmssd_ms: Optional[float]

    # ── Data quality ──────────────────────────────────────────────────────────
    windows_valid: int
    windows_total: int
    data_quality:  float   # windows_valid / windows_total

    # ── Practice (defaults last — dataclass ordering requirement) ─────────────
    practice_type:    str            = "resonance_hold"   # see sessions/practice_registry.py
    attention_anchor: Optional[str]  = None               # "belly"|"heart"|"solar"|"root"|"brow"

    # ── Notes ─────────────────────────────────────────────────────────────────
    notes: list[str] = field(default_factory=list)

    def is_scoreable(self) -> bool:
        """True if enough valid windows exist for a meaningful session score."""
        return self.session_score is not None and self.data_quality >= 0.5

    def rmssd_improved(self) -> bool:
        """True if post-session RMSSD is higher than pre-session."""
        if self.rmssd_delta_ms is None:
            return False
        return self.rmssd_delta_ms > 0


# ── Public API ─────────────────────────────────────────────────────────────────

def compute_session_outcome(
    coherence_windows: list[CoherenceResult],
    *,
    session_id: Optional[str] = None,
    session_date: Optional[date] = None,
    duration_minutes: int = 0,
    session_type: str = "full",
    practice_type: str = "resonance_hold",
    attention_anchor: Optional[str] = None,
    pre_window_metrics: Optional[PPIMetrics] = None,
    post_window_metrics: Optional[PPIMetrics] = None,
    morning_rmssd_ms: Optional[float] = None,
    personal_floor_rmssd: Optional[float] = None,
    window_duration_seconds: int = 60,
) -> SessionOutcome:
    """
    Compute SessionOutcome from a completed session record.

    Parameters
    ----------
    coherence_windows : list[CoherenceResult]
        Ordered list of CoherenceResult objects, one per analysis window.
        Invalid windows (is_valid() == False) are excluded from quality metrics
        but counted in windows_total.
    session_id : str | None
        UUID — generated if not provided.
    session_date : date | None
        Session date — defaults to today.
    duration_minutes : int
        Actual session duration in minutes.
    session_type : str
        "breathing_only" | "full" | "active_recovery" | "rest"
    pre_window_metrics : PPIMetrics | None
        HRV metrics from the 2-minute window immediately before guided breathing.
    post_window_metrics : PPIMetrics | None
        HRV metrics from the final 2 minutes of the session.
    morning_rmssd_ms : float | None
        Morning RMSSD reading (context only — not used in score).
    personal_floor_rmssd : float | None
        User's personal RMSSD floor from PersonalFingerprint.
        Used to compute rmssd_delta_pct (personal-relative).
    window_duration_seconds : int
        Duration of each coherence window in seconds. Used for arc timing.

    Returns
    -------
    SessionOutcome
    """
    sid   = session_id or str(uuid.uuid4())
    sdate = session_date or date.today()

    total   = len(coherence_windows)
    valid   = [w for w in coherence_windows if w.is_valid()]
    n_valid = len(valid)

    quality = n_valid / total if total > 0 else 0.0
    notes: list[str] = []

    if total == 0:
        notes.append("no_windows_recorded")
        return _empty_outcome(sid, sdate, duration_minutes, session_type,
                              morning_rmssd_ms, notes,
                              practice_type=practice_type,
                              attention_anchor=attention_anchor)

    if quality < 0.5:
        notes.append(f"low_data_quality:{quality:.2f}")

    # ── Coherence metrics ──────────────────────────────────────────────────────
    coherence_values = [w.coherence for w in valid if w.coherence is not None]

    if not coherence_values:
        coherence_avg  = None
        coherence_peak = None
        zone_3_plus    = None
        session_score  = None
    else:
        coherence_avg  = float(np.mean(coherence_values))
        coherence_peak = float(np.max(coherence_values))

        zone_3_plus_count = sum(
            1 for w in valid
            if w.zone is not None and w.zone >= 3
        )
        zone_3_plus = zone_3_plus_count / n_valid if n_valid > 0 else 0.0

        session_score = _compute_session_score(coherence_avg, coherence_peak, zone_3_plus)

    # ── Pre/post RMSSD delta ───────────────────────────────────────────────────
    pre_rmssd  = pre_window_metrics.rmssd_ms  if pre_window_metrics  and pre_window_metrics.is_valid()  else None
    post_rmssd = post_window_metrics.rmssd_ms if post_window_metrics and post_window_metrics.is_valid() else None

    rmssd_delta_ms  = None
    rmssd_delta_pct = None

    if pre_rmssd is not None and post_rmssd is not None:
        rmssd_delta_ms = round(post_rmssd - pre_rmssd, 2)
        if pre_rmssd > 0:
            rmssd_delta_pct = round(rmssd_delta_ms / pre_rmssd, 4)
        if rmssd_delta_ms > 0:
            notes.append("rmssd_improved")
        elif rmssd_delta_ms < -5.0:
            notes.append("rmssd_declined")

    # ── Recovery arc ──────────────────────────────────────────────────────────
    arc_completed, arc_duration_hours = _detect_arc(
        valid, window_duration_seconds=window_duration_seconds
    )
    if arc_completed:
        notes.append("arc_completed")

    return SessionOutcome(
        session_id       = sid,
        session_date     = sdate,
        duration_minutes = duration_minutes,
        session_type     = session_type,
        practice_type    = practice_type,
        attention_anchor = attention_anchor,
        coherence_avg        = round(coherence_avg, 4) if coherence_avg is not None else None,
        coherence_peak       = round(coherence_peak, 4) if coherence_peak is not None else None,
        time_in_zone_3_plus  = round(zone_3_plus, 4)   if zone_3_plus   is not None else None,
        session_score        = round(session_score, 4)  if session_score  is not None else None,
        pre_rmssd_ms     = round(pre_rmssd, 2)  if pre_rmssd  is not None else None,
        post_rmssd_ms    = round(post_rmssd, 2) if post_rmssd is not None else None,
        rmssd_delta_ms   = rmssd_delta_ms,
        rmssd_delta_pct  = rmssd_delta_pct,
        arc_completed    = arc_completed,
        arc_duration_hours = arc_duration_hours,
        morning_rmssd_ms = morning_rmssd_ms,
        windows_valid    = n_valid,
        windows_total    = total,
        data_quality     = round(quality, 4),
        notes            = notes,
    )


# ── Aggregation helpers (used by level_gate and weekly summaries) ─────────────

def coherence_avg_last_n(outcomes: list[SessionOutcome], n: int = 3) -> Optional[float]:
    """Mean coherence_avg across the last N scoreable sessions."""
    scoreable = [o for o in outcomes if o.coherence_avg is not None][-n:]
    if not scoreable:
        return None
    return float(np.mean([o.coherence_avg for o in scoreable]))


def coherence_peak_avg(outcomes: list[SessionOutcome]) -> Optional[float]:
    """Mean coherence_peak across all scoreable sessions."""
    peaks = [o.coherence_peak for o in outcomes if o.coherence_peak is not None]
    if not peaks:
        return None
    return float(np.mean(peaks))


def rmssd_delta_positive_fraction(outcomes: list[SessionOutcome]) -> float:
    """
    Fraction of sessions where post-session RMSSD was higher than pre-session.
    Returns 0.0 if no sessions had a measurable delta.
    """
    with_delta = [o for o in outcomes if o.rmssd_delta_ms is not None]
    if not with_delta:
        return 0.0
    positive = sum(1 for o in with_delta if o.rmssd_delta_ms > 0)
    return positive / len(with_delta)


def arc_completion_fraction(outcomes: list[SessionOutcome]) -> float:
    """Fraction of sessions where a full recovery arc was completed."""
    if not outcomes:
        return 0.0
    return sum(1 for o in outcomes if o.arc_completed) / len(outcomes)


def data_quality_avg(outcomes: list[SessionOutcome]) -> float:
    """Mean data_quality across all sessions."""
    if not outcomes:
        return 0.0
    return float(np.mean([o.data_quality for o in outcomes]))


def arc_duration_trend(
    outcomes: list[SessionOutcome],
    *,
    baseline_n: int = 6,
    recent_n: int = 3,
) -> str:
    """
    Compare arc duration in the most recent sessions vs the first baseline sessions.

    Returns
    -------
    "shortening" | "stable" | "lengthening" | "insufficient_data"
    """
    completed = [o for o in outcomes if o.arc_completed and o.arc_duration_hours is not None]
    if len(completed) < baseline_n + recent_n:
        return "insufficient_data"

    baseline_mean = float(np.mean([o.arc_duration_hours for o in completed[:baseline_n]]))
    recent_mean   = float(np.mean([o.arc_duration_hours for o in completed[-recent_n:]]))

    delta_hours = recent_mean - baseline_mean
    if delta_hours < -0.33:         # >20 minutes faster
        return "shortening"
    if delta_hours > 0.33:          # >20 minutes slower
        return "lengthening"
    return "stable"


# ── Private helpers ────────────────────────────────────────────────────────────

def _compute_session_score(
    coherence_avg: float,
    coherence_peak: float,
    time_in_zone_3_plus: float,
) -> float:
    """
    Composite session score (0.0–1.0).

    Weights:
        coherence_avg       × 0.40  (breadth — sustained quality)
        coherence_peak      × 0.30  (ceiling — how high did the system get)
        time_in_zone_3_plus × 0.30  (sustained zone 3+ quality)
    """
    score = (
        coherence_avg       * _W_COHERENCE_AVG
        + coherence_peak    * _W_COHERENCE_PEAK
        + time_in_zone_3_plus * _W_ZONE_3_PLUS
    )
    return float(np.clip(score, 0.0, 1.0))


def _detect_arc(
    valid_windows: list[CoherenceResult],
    *,
    window_duration_seconds: int = 60,
) -> tuple[bool, Optional[float]]:
    """
    Detect whether a coherence recovery arc completed during the session.

    Arc definition:
        1. Session starts at or below _ARC_START_CEILING coherence
        2. Coherence rises at least _ARC_RISE_MINIMUM above the starting value
        3. That elevated state is sustained for at least _ARC_SUSTAIN_WINDOWS
           consecutive windows

    Returns
    -------
    (arc_completed: bool, arc_duration_hours: float | None)
        arc_duration_hours = time from window 0 to the first window where
        the sustained elevated state begins
    """
    if len(valid_windows) < _ARC_SUSTAIN_WINDOWS + 1:
        return False, None

    coherences = [
        w.coherence for w in valid_windows if w.coherence is not None
    ]
    if not coherences:
        return False, None

    start_coherence = coherences[0]
    if start_coherence > _ARC_START_CEILING:
        # Session didn't start low enough to qualify as an arc
        return False, None

    threshold = start_coherence + _ARC_RISE_MINIMUM

    # Scan for _ARC_SUSTAIN_WINDOWS consecutive windows all above threshold
    consecutive = 0
    for i, c in enumerate(coherences):
        if c >= threshold:
            consecutive += 1
            if consecutive >= _ARC_SUSTAIN_WINDOWS:
                # Arc completed at window (i - _ARC_SUSTAIN_WINDOWS + 1)
                arc_peak_window = i - _ARC_SUSTAIN_WINDOWS + 1
                arc_seconds = arc_peak_window * window_duration_seconds
                arc_hours   = round(arc_seconds / 3600.0, 3)
                return True, arc_hours
        else:
            consecutive = 0

    return False, None


def _empty_outcome(
    session_id: str,
    session_date: date,
    duration_minutes: int,
    session_type: str,
    morning_rmssd_ms: Optional[float],
    notes: list[str],
    *,
    practice_type: str = "resonance_hold",
    attention_anchor: Optional[str] = None,
) -> SessionOutcome:
    return SessionOutcome(
        session_id       = session_id,
        session_date     = session_date,
        duration_minutes = duration_minutes,
        session_type     = session_type,
        practice_type    = practice_type,
        attention_anchor = attention_anchor,
        coherence_avg        = None,
        coherence_peak       = None,
        time_in_zone_3_plus  = None,
        session_score        = None,
        pre_rmssd_ms     = None,
        post_rmssd_ms    = None,
        rmssd_delta_ms   = None,
        rmssd_delta_pct  = None,
        arc_completed    = False,
        arc_duration_hours = None,
        morning_rmssd_ms = morning_rmssd_ms,
        windows_valid    = 0,
        windows_total    = 0,
        data_quality     = 0.0,
        notes            = notes,
    )
