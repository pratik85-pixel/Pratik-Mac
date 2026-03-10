"""
tracking/stress_detector.py

Detects stress events from a sequence of BackgroundWindowResult objects.

Algorithm:
    1. For each valid window, compare rmssd_ms against the user's personal morning average.
    2. A window "breaches" if rmssd_ms < personal_morning_avg × STRESS_THRESHOLD_PCT
       OR if rmssd dropped > STRESS_RATE_TRIGGER_PCT compared to the previous window.
    3. Consecutive breaching windows are merged into candidate events.
    4. A candidate becomes a StressWindowResult if it spans >= STRESS_MIN_WINDOWS windows.
    5. Adjacent events with gap <= STRESS_MERGE_GAP_MINUTES are merged into one.
    6. Each event records max suppression, duration, and a tag candidate based on motion.

Motion differentiation:
    - Windows with acc_mean > MOTION_ACTIVE_THRESHOLD → "physical_load_candidate"
    - Else → "stress_event_candidate"
    - Majority-vote across windows in the event determines the event's tag_candidate.

Stress contribution:
    Each event's contribution to daily stress load is:
        contribution = suppression_area_event / max_possible_suppression_area_day
    where suppression_area = Σ max(0, morning_avg - window_rmssd) × window_duration_min
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from config import CONFIG
from tracking.background_processor import BackgroundWindowResult, has_motion


@dataclass
class StressWindowResult:
    """
    A detected continuous stress episode.
    Written to the StressWindow DB table.
    """
    user_id:                  str
    started_at:               datetime
    ended_at:                 datetime
    duration_minutes:         float

    # How deep did it go?
    rmssd_min_ms:             float       # lowest RMSSD seen in this window
    suppression_pct:          float       # how far below personal avg at the nadir (0.0–1.0+)

    # Contribution to daily stress load (filled by daily_summarizer after all events known)
    stress_contribution_pct:  Optional[float] = None   # % of daily total, 0–100

    # Raw suppression area (minutes × ms below avg) for recompute support
    suppression_area:         float = 0.0

    # Tagging
    tag:                      Optional[str] = None       # user-confirmed tag
    tag_candidate:            Optional[str] = None       # "physical_load_candidate" | "stress_event_candidate"
    tag_source:               Optional[str] = None       # "auto_detected" | "user_confirmed" | "auto_tagged"

    # Nudge
    nudge_sent:               bool = False
    nudge_responded:          bool = False

    # Source windows (not persisted — used during computation)
    _source_windows:          list = field(default_factory=list, repr=False, compare=False)


def detect_stress_windows(
    windows: list[BackgroundWindowResult],
    personal_morning_avg: float,
    personal_floor: float,
    wake_ts: Optional[datetime] = None,
    sleep_ts: Optional[datetime] = None,
) -> list[StressWindowResult]:
    """
    Detect stress events from a day's worth of BackgroundWindowResult objects.

    Parameters
    ----------
    windows : list[BackgroundWindowResult]
        5-minute background windows for the day. Must all have context="background".
        Should be sorted by window_start ascending.
        Invalid windows (is_valid=False) are skipped.
    personal_morning_avg : float
        User's personal RMSSD morning average (from PersonalModel.rmssd_morning_avg).
        This is the normalization reference: 100% = this value.
    personal_floor : float
        User's personal RMSSD floor (5th percentile). Used as a sanity lower bound.
    wake_ts : datetime, optional
        If provided, only windows at or after wake_ts are included.
    sleep_ts : datetime, optional
        If provided, only windows before sleep_ts are included.

    Returns
    -------
    list[StressWindowResult]
        Detected stress events, sorted by start time.
    """
    cfg = CONFIG.tracking

    # Filter: valid, background context, within waking hours
    valid = [
        w for w in windows
        if w.is_valid
        and w.context == "background"
        and (wake_ts is None or w.window_start >= wake_ts)
        and (sleep_ts is None or w.window_end <= sleep_ts)
    ]

    if not valid:
        return []

    threshold_rmssd = personal_morning_avg * cfg.STRESS_THRESHOLD_PCT
    window_duration = cfg.BACKGROUND_WINDOW_MINUTES

    # Step 1: mark each window as breaching or not
    breaching: list[bool] = []
    prev_rmssd: Optional[float] = None

    for w in valid:
        rmssd = w.rmssd_ms  # type: ignore[assignment]
        assert rmssd is not None  # guaranteed by is_valid=True

        # Threshold breach
        threshold_breach = rmssd < threshold_rmssd

        # Rate-of-change trigger (acute spike detection)
        rate_breach = False
        if prev_rmssd is not None:
            drop_pct = (prev_rmssd - rmssd) / prev_rmssd
            rate_breach = drop_pct > cfg.STRESS_RATE_TRIGGER_PCT

        breaching.append(threshold_breach or rate_breach)
        prev_rmssd = rmssd

    # Step 2: group consecutive breaching windows into raw candidates
    candidates: list[list[BackgroundWindowResult]] = []
    current_group: list[BackgroundWindowResult] = []

    for w, is_breach in zip(valid, breaching):
        if is_breach:
            current_group.append(w)
        else:
            if current_group:
                candidates.append(current_group)
                current_group = []
    if current_group:
        candidates.append(current_group)

    # Step 3: filter candidates by minimum window count
    candidates = [g for g in candidates if len(g) >= cfg.STRESS_MIN_WINDOWS]

    # Step 4: merge adjacent candidates with gap <= MERGE_GAP_MINUTES
    if len(candidates) > 1:
        merged: list[list[BackgroundWindowResult]] = [candidates[0]]
        for group in candidates[1:]:
            prev_end = merged[-1][-1].window_end
            curr_start = group[0].window_start
            gap_minutes = (curr_start - prev_end).total_seconds() / 60.0
            if gap_minutes <= cfg.STRESS_MERGE_GAP_MINUTES:
                merged[-1].extend(group)
            else:
                merged.append(group)
        candidates = merged

    # Step 5: build StressWindowResult for each candidate
    results: list[StressWindowResult] = []

    for group in candidates:
        rmssd_values = [w.rmssd_ms for w in group]  # all not None after filter
        rmssd_min = min(rmssd_values)  # type: ignore[type-var]

        suppression_at_nadir = (personal_morning_avg - rmssd_min) / personal_morning_avg

        # Compute suppression area: Σ (avg - rmssd) × duration for below-avg windows
        suppression_area = sum(
            max(0.0, personal_morning_avg - w.rmssd_ms) * window_duration  # type: ignore[operator]
            for w in group
        )

        # Tag candidate: majority vote on motion
        physical_count = sum(1 for w in group if has_motion(w))
        total = len(group)
        tag_candidate = (
            "physical_load_candidate"
            if physical_count / total >= 0.5
            else "stress_event_candidate"
        )

        result = StressWindowResult(
            user_id=group[0].user_id,
            started_at=group[0].window_start,
            ended_at=group[-1].window_end,
            duration_minutes=float(len(group) * window_duration),
            rmssd_min_ms=float(rmssd_min),
            suppression_pct=round(suppression_at_nadir, 3),
            suppression_area=round(suppression_area, 2),
            tag=None,
            tag_candidate=tag_candidate,
            tag_source="auto_detected",
        )
        result._source_windows = group
        results.append(result)

    return results


def compute_stress_contributions(
    stress_windows: list[StressWindowResult],
    max_possible_suppression_area: float,
) -> list[StressWindowResult]:
    """
    Fill in stress_contribution_pct on each StressWindowResult once the
    max_possible_suppression_area for the day is known.

    Parameters
    ----------
    stress_windows : list[StressWindowResult]
        Output of detect_stress_windows — contribution_pct fields will be None.
    max_possible_suppression_area : float
        (personal_morning_avg - personal_floor) × waking_minutes
        Computed by daily_summarizer after wake/sleep boundaries are determined.

    Returns
    -------
    list[StressWindowResult]
        Same list, mutated in-place with contribution_pct filled.
    """
    if max_possible_suppression_area <= 0:
        for sw in stress_windows:
            sw.stress_contribution_pct = 0.0
        return stress_windows

    for sw in stress_windows:
        sw.stress_contribution_pct = round(
            (sw.suppression_area / max_possible_suppression_area) * 100.0, 1
        )
    return stress_windows


def should_nudge(
    sw: StressWindowResult,
    daily_stress_load: float,
    nudges_sent_today: int,
) -> bool:
    """
    Determine whether a stress window should trigger a tagging nudge.

    Rules:
        - Never nudge if already tagged (tag is not None)
        - Normal nudge: contribution > MIN_NUDGE_CONTRIBUTION and daily cap not hit
        - Significant spike override: contribution > SIGNIFICANT_OVERRIDE threshold
          fires even if cap is hit
    """
    if sw.tag is not None:
        return False

    cfg = CONFIG.tracking
    contribution_pct = (sw.stress_contribution_pct or 0.0) / 100.0

    if contribution_pct < cfg.STRESS_MIN_NUDGE_CONTRIBUTION:
        return False

    # Cap reached — only fire for significant spikes
    if nudges_sent_today >= cfg.MAX_TAGGING_NUDGES_PER_DAY:
        return contribution_pct >= cfg.NUDGE_SIGNIFICANT_SPIKE_OVERRIDE_PCT

    return True
