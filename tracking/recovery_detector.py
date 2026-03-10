"""
tracking/recovery_detector.py

Detects recovery windows from a sequence of BackgroundWindowResult objects.

A recovery window is a sustained period (≥ RECOVERY_MIN_WINDOWS × 5 min) where
RMSSD is at or above the user's personal morning average. These represent moments
when the ANS is in net-recovery territory — depositing credit into the daily
recovery account.

Recovery sources:
    - Sleep windows (context="sleep"): auto-tagged, highest weight
    - ZenFlow sessions: identified by session_id reference, auto-tagged
    - Daytime recovery windows (context="background", RMSSD ≥ avg): prompt user to tag

Recovery credit area:
    Symmetric with stress suppression area.
    credit_area = Σ max(0, rmssd_window - personal_morning_avg) × window_duration_min
    for all windows above threshold.

    This area is normalized against the max_possible_recovery_area in daily_summarizer
    to produce the 0–100 recovery score.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from config import CONFIG
from tracking.background_processor import BackgroundWindowResult


@dataclass
class RecoveryWindowResult:
    """
    A detected continuous recovery episode.
    Written to the RecoveryWindow DB table.
    """
    user_id:                  str
    started_at:               datetime
    ended_at:                 datetime
    duration_minutes:         float
    context:                  str       # "background" | "sleep"

    # How much recovery credit did this window provide?
    rmssd_avg_ms:             float
    recovery_area:            float     # Σ (rmssd - avg) × duration_minutes, for above-avg windows
    recovery_contribution_pct: Optional[float] = None   # % of daily recovery total

    # Tagging
    tag:                      Optional[str] = None
    # "sleep" | "zenflow_session" | "walk" | "exercise_recovery" | "recovery_window"
    tag_source:               Optional[str] = None
    # "auto_confirmed" | "user_confirmed" | "auto_tagged"

    # FK link to ZenFlow session if applicable
    zenflow_session_id:       Optional[str] = None

    # Source windows (not persisted)
    _source_windows:          list = field(default_factory=list, repr=False, compare=False)


def detect_recovery_windows(
    windows: list[BackgroundWindowResult],
    personal_morning_avg: float,
    wake_ts: Optional[datetime] = None,
    sleep_ts: Optional[datetime] = None,
    zenflow_session_intervals: Optional[list[tuple[datetime, datetime, str]]] = None,
) -> list[RecoveryWindowResult]:
    """
    Detect recovery windows from a day's BackgroundWindowResult objects.

    Parameters
    ----------
    windows : list[BackgroundWindowResult]
        All background + sleep windows for the day, sorted by window_start ascending.
        Valid and invalid windows both accepted — invalids are skipped.
    personal_morning_avg : float
        User's personal RMSSD morning average. Windows at or above this level
        contribute recovery credit.
    wake_ts : datetime, optional
        Windows before wake_ts are excluded from daytime recovery detection.
        Sleep windows (context="sleep") are always included regardless.
    sleep_ts : datetime, optional
        Windows after sleep_ts are excluded from daytime detection.
    zenflow_session_intervals : list of (start, end, session_id), optional
        If provided, recovery windows overlapping a ZenFlow session are auto-tagged.

    Returns
    -------
    list[RecoveryWindowResult]
        Detected recovery windows, sorted by start time.
    """
    cfg = CONFIG.tracking
    window_duration = cfg.BACKGROUND_WINDOW_MINUTES

    # Separate sleep and background windows
    sleep_wins = [
        w for w in windows
        if w.is_valid and w.context == "sleep"
    ]
    background_wins = [
        w for w in windows
        if w.is_valid
        and w.context == "background"
        and (wake_ts is None or w.window_start >= wake_ts)
        and (sleep_ts is None or w.window_end <= sleep_ts)
    ]

    results: list[RecoveryWindowResult] = []

    # ── Sleep windows ────────────────────────────────────────────────────────
    # Treat the entire sleep period as one recovery window.
    # Sleep is too fragmented in HRV (NREM/REM cycles dip and rise) to detect
    # individual peaks as recovery events — instead, aggregate into one block.
    if sleep_wins:
        rmssd_values = [w.rmssd_ms for w in sleep_wins if w.rmssd_ms is not None]
        if rmssd_values:
            rmssd_avg = sum(rmssd_values) / len(rmssd_values)
            # Credit area: total time × max(0, rmssd - avg) for each window
            credit_area = sum(
                max(0.0, (w.rmssd_ms or 0.0) - personal_morning_avg) * window_duration
                for w in sleep_wins
            )
            results.append(RecoveryWindowResult(
                user_id=sleep_wins[0].user_id,
                started_at=sleep_wins[0].window_start,
                ended_at=sleep_wins[-1].window_end,
                duration_minutes=float(len(sleep_wins) * window_duration),
                context="sleep",
                rmssd_avg_ms=round(rmssd_avg, 1),
                recovery_area=round(credit_area, 2),
                tag="sleep",
                tag_source="auto_confirmed",
            ))

    # ── Daytime recovery windows ─────────────────────────────────────────────
    threshold_rmssd = personal_morning_avg * cfg.RECOVERY_THRESHOLD_PCT

    # Group consecutive windows at or above threshold
    above: list[bool] = [
        (w.rmssd_ms is not None and w.rmssd_ms >= threshold_rmssd)
        for w in background_wins
    ]

    current_group: list[BackgroundWindowResult] = []
    groups: list[list[BackgroundWindowResult]] = []

    for w, is_above in zip(background_wins, above):
        if is_above:
            current_group.append(w)
        else:
            if current_group:
                groups.append(current_group)
                current_group = []
    if current_group:
        groups.append(current_group)

    # Filter: minimum windows
    groups = [g for g in groups if len(g) >= cfg.RECOVERY_MIN_WINDOWS]

    # Build RecoveryWindowResult for each daytime group
    for group in groups:
        rmssd_values = [w.rmssd_ms for w in group if w.rmssd_ms is not None]
        rmssd_avg = sum(rmssd_values) / len(rmssd_values) if rmssd_values else 0.0

        credit_area = sum(
            max(0.0, (w.rmssd_ms or 0.0) - personal_morning_avg) * window_duration
            for w in group
        )

        # Auto-tag if overlaps a ZenFlow session
        tag: Optional[str] = None
        tag_source: Optional[str] = None
        zenflow_session_id: Optional[str] = None

        group_start = group[0].window_start
        group_end = group[-1].window_end

        if zenflow_session_intervals:
            for sess_start, sess_end, sess_id in zenflow_session_intervals:
                # Overlap check
                if group_start < sess_end and group_end > sess_start:
                    tag = "zenflow_session"
                    tag_source = "auto_confirmed"
                    zenflow_session_id = sess_id
                    break

        rw = RecoveryWindowResult(
            user_id=group[0].user_id,
            started_at=group_start,
            ended_at=group_end,
            duration_minutes=float(len(group) * window_duration),
            context="background",
            rmssd_avg_ms=round(rmssd_avg, 1),
            recovery_area=round(credit_area, 2),
            tag=tag,
            tag_source=tag_source,
            zenflow_session_id=zenflow_session_id,
        )
        rw._source_windows = group
        results.append(rw)

    # Sort all by start time
    results.sort(key=lambda r: r.started_at)
    return results


def compute_recovery_contributions(
    recovery_windows: list[RecoveryWindowResult],
    max_possible_recovery_area: float,
) -> list[RecoveryWindowResult]:
    """
    Fill in recovery_contribution_pct on each RecoveryWindowResult once the
    max_possible_recovery_area for the day is known.
    """
    if max_possible_recovery_area <= 0:
        for rw in recovery_windows:
            rw.recovery_contribution_pct = 0.0
        return recovery_windows

    for rw in recovery_windows:
        rw.recovery_contribution_pct = round(
            (rw.recovery_area / max_possible_recovery_area) * 100.0, 1
        )
    return recovery_windows
