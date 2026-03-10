"""
model/recovery_arc_detector.py

Detect RMSSD recovery arc events from a time series.

Definition:
    A recovery arc event starts when RMSSD drops ≥ DROP_THRESHOLD_PCT below
    a rolling personal baseline and ends when RMSSD returns to ≥
    RECOVERY_ARC_RETURN_THRESHOLD_PCT of that same baseline.

    Arc duration = end_ts - drop_ts  (in hours)

    This is the single most important resilience metric in ZenFlow.
    It captures HOW FAST you bounce back — not just how high your HRV is.

Three arc classes (matching config/scoring.py):
    fast     < 2 hrs
    normal   2–6 hrs
    slow     6–12 hrs
    compressed > 12 hrs  (often doesn't fully recover overnight)

Algorithm:
    1. Build a rolling 2-hour median baseline (robust to noise).
    2. When current RMSSD < baseline × (1 - DROP_THRESHOLD_PCT): arc starts.
    3. Track minimum (nadir) during the arc.
    4. When RMSSD ≥ baseline × RECOVERY_ARC_RETURN_THRESHOLD_PCT: arc ends.
    5. If no return within MAX_ARC_HOURS: arc is marked "incomplete".
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

from config import CONFIG


class ArcClass(str, Enum):
    FAST       = "fast"        # < 2 hrs
    NORMAL     = "normal"      # 2–6 hrs
    SLOW       = "slow"        # 6–12 hrs
    COMPRESSED = "compressed"  # > 12 hrs
    INCOMPLETE = "incomplete"  # no return observed


@dataclass
class RecoveryArcEvent:
    """One complete (or incomplete) recovery arc."""
    drop_ts:          datetime
    nadir_ts:         datetime
    return_ts:        Optional[datetime]    # None if incomplete
    baseline_at_drop: float                 # RMSSD ms — rolling baseline when drop started
    nadir_value:      float                 # RMSSD ms — lowest point
    return_value:     Optional[float]       # RMSSD ms — value at return
    duration_hours:   Optional[float]       # None if incomplete
    arc_class:        ArcClass
    drop_depth_pct:   float                 # how far below baseline (0–1)
    context_tags:     list[str] = field(default_factory=list)  # e.g. ["post_alcohol", "poor_sleep"]

    def is_complete(self) -> bool:
        return self.return_ts is not None


@dataclass
class RecoveryArcSummary:
    """Summary statistics across all arc events for a user."""
    mean_hours:    Optional[float]
    fast_hours:    Optional[float]    # typical fast-end
    slow_hours:    Optional[float]    # typical slow-end
    arc_class:     ArcClass
    n_events:      int
    n_incomplete:  int

    def to_dict(self) -> dict:
        return {
            "mean_hours":   self.mean_hours,
            "fast_hours":   self.fast_hours,
            "slow_hours":   self.slow_hours,
            "arc_class":    self.arc_class.value,
            "n_events":     self.n_events,
            "n_incomplete": self.n_incomplete,
        }


# ── Constants ──────────────────────────────────────────────────────────────────
_DROP_THRESHOLD_PCT = 0.20      # ≥20% drop from rolling baseline triggers arc
_ROLLING_WINDOW_HOURS = 2.0     # baseline window
_MAX_ARC_HOURS = 24.0           # beyond this → incomplete arc
_MIN_DROP_DURATION_READINGS = 2  # need ≥2 consecutive low readings to count


def detect_arcs(
    rmssd_values: np.ndarray,
    timestamps: np.ndarray,          # Unix seconds or datetime objects
    context_map: Optional[dict] = None,  # ts → context tag (optional)
) -> list[RecoveryArcEvent]:
    """
    Detect recovery arc events from an RMSSD time series.

    Parameters
    ----------
    rmssd_values : np.ndarray
        RMSSD values in ms (clean, confidence-filtered).
    timestamps : np.ndarray
        Corresponding timestamps as Unix float seconds.
    context_map : dict | None
        Optional mapping from timestamp (float, rounded to nearest minute)
        to a context tag string (e.g. "post_alcohol").

    Returns
    -------
    list[RecoveryArcEvent] ordered by drop_ts ascending.
    """
    cfg = CONFIG.scoring
    n = len(rmssd_values)
    if n < 4:
        return []

    events: list[RecoveryArcEvent] = []

    # Convert timestamps to float seconds if datetime
    if hasattr(timestamps[0], "timestamp"):
        ts_sec = np.array([t.timestamp() for t in timestamps], dtype=np.float64)
    else:
        ts_sec = timestamps.astype(np.float64)

    rolling_window_sec = _ROLLING_WINDOW_HOURS * 3600.0
    return_threshold = cfg.RECOVERY_ARC_RETURN_THRESHOLD_PCT

    in_arc = False
    arc_start_idx = None
    arc_nadir_idx = None
    arc_baseline = None

    for i in range(n):
        # ── Rolling baseline: median of readings in past ROLLING_WINDOW_HOURS ─
        window_mask = (ts_sec >= ts_sec[i] - rolling_window_sec) & (ts_sec < ts_sec[i])
        if window_mask.sum() >= 3:
            baseline = float(np.median(rmssd_values[window_mask]))
        else:
            # Not enough history yet — use mean of available readings up to i
            baseline = float(np.mean(rmssd_values[:i + 1]))

        current = float(rmssd_values[i])

        if not in_arc:
            # Check for drop
            if baseline > 0 and (current < baseline * (1.0 - _DROP_THRESHOLD_PCT)):
                in_arc = True
                arc_start_idx = i
                arc_nadir_idx = i
                arc_baseline = baseline
        else:
            # Track nadir
            if current < rmssd_values[arc_nadir_idx]:
                arc_nadir_idx = i

            # Check for return
            return_target = arc_baseline * return_threshold
            arc_duration_hrs = (ts_sec[i] - ts_sec[arc_start_idx]) / 3600.0

            if current >= return_target:
                # Arc complete
                drop_depth = (arc_baseline - float(rmssd_values[arc_nadir_idx])) / arc_baseline
                duration = arc_duration_hrs

                # Classify
                arc_class = _classify_arc(duration)

                # Context tags
                tags = []
                if context_map:
                    tag = context_map.get(round(ts_sec[arc_start_idx] / 60) * 60)
                    if tag:
                        tags.append(tag)

                events.append(RecoveryArcEvent(
                    drop_ts=_to_datetime(ts_sec[arc_start_idx]),
                    nadir_ts=_to_datetime(ts_sec[arc_nadir_idx]),
                    return_ts=_to_datetime(ts_sec[i]),
                    baseline_at_drop=arc_baseline,
                    nadir_value=float(rmssd_values[arc_nadir_idx]),
                    return_value=current,
                    duration_hours=round(duration, 2),
                    arc_class=arc_class,
                    drop_depth_pct=round(drop_depth, 3),
                    context_tags=tags,
                ))
                in_arc = False
                arc_start_idx = None

            elif arc_duration_hrs > _MAX_ARC_HOURS:
                # Incomplete arc
                drop_depth = (arc_baseline - float(rmssd_values[arc_nadir_idx])) / arc_baseline
                events.append(RecoveryArcEvent(
                    drop_ts=_to_datetime(ts_sec[arc_start_idx]),
                    nadir_ts=_to_datetime(ts_sec[arc_nadir_idx]),
                    return_ts=None,
                    baseline_at_drop=arc_baseline,
                    nadir_value=float(rmssd_values[arc_nadir_idx]),
                    return_value=None,
                    duration_hours=None,
                    arc_class=ArcClass.INCOMPLETE,
                    drop_depth_pct=round(drop_depth, 3),
                    context_tags=[],
                ))
                in_arc = False

    # Handle arc still open at end of data
    if in_arc and arc_start_idx is not None:
        drop_depth = (arc_baseline - float(rmssd_values[arc_nadir_idx])) / arc_baseline
        events.append(RecoveryArcEvent(
            drop_ts=_to_datetime(ts_sec[arc_start_idx]),
            nadir_ts=_to_datetime(ts_sec[arc_nadir_idx]),
            return_ts=None,
            baseline_at_drop=arc_baseline,
            nadir_value=float(rmssd_values[arc_nadir_idx]),
            return_value=None,
            duration_hours=None,
            arc_class=ArcClass.INCOMPLETE,
            drop_depth_pct=round(drop_depth, 3),
            context_tags=[],
        ))

    return events


def summarise_arcs(events: list[RecoveryArcEvent]) -> RecoveryArcSummary:
    """
    Compute summary statistics across a list of arc events.

    Ignores incomplete arcs for duration statistics (they would skew low).
    """
    if not events:
        return RecoveryArcSummary(
            mean_hours=None, fast_hours=None, slow_hours=None,
            arc_class=ArcClass.NORMAL, n_events=0, n_incomplete=0,
        )

    complete = [e for e in events if e.is_complete()]
    incomplete = [e for e in events if not e.is_complete()]

    if not complete:
        return RecoveryArcSummary(
            mean_hours=None, fast_hours=None, slow_hours=None,
            arc_class=ArcClass.INCOMPLETE, n_events=len(events),
            n_incomplete=len(incomplete),
        )

    durations = np.array([e.duration_hours for e in complete], dtype=np.float64)
    mean_hrs = float(np.mean(durations))
    fast_hrs = float(np.percentile(durations, 25))
    slow_hrs = float(np.percentile(durations, 75))

    # Overall classification based on mean
    arc_class = _classify_arc(mean_hrs)

    return RecoveryArcSummary(
        mean_hours=round(mean_hrs, 2),
        fast_hours=round(fast_hrs, 2),
        slow_hours=round(slow_hrs, 2),
        arc_class=arc_class,
        n_events=len(events),
        n_incomplete=len(incomplete),
    )


def _classify_arc(duration_hours: float) -> ArcClass:
    if duration_hours < 2.0:
        return ArcClass.FAST
    if duration_hours < 6.0:
        return ArcClass.NORMAL
    if duration_hours < 12.0:
        return ArcClass.SLOW
    return ArcClass.COMPRESSED


def _to_datetime(ts_sec: float) -> datetime:
    return datetime.utcfromtimestamp(ts_sec)
