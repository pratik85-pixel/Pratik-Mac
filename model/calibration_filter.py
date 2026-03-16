"""
model/calibration_filter.py

3-pass artifact filter for end-of-day calibration batches.

Called by _run_calibration_batch() in tracking_service.py with the full
history of background_windows for a user. Returns clean windows + rejection
stats so the batch can compute trustworthy floor/ceiling/morning_avg values.

Filter passes (in order):
  Pass 1 — Settling discard:  remove all windows within 30 min of the user's
            first-ever window_start (optical PPG needs 15–30 min to settle on
            first wear).
  Pass 2 — Temporal spike gate: reject any window whose rmssd_ms exceeds
            2.5 × the rolling median of the ±6 surrounding windows.
  Pass 3 — Population ceiling gate: unconditionally reject rmssd_ms > 110.0ms
            (99th percentile of healthy adult RMSSD — anything above is
            optical artifact, not physiology).

Confidence scoring:
  - Starts at 1.0.
  - Decreases by 0.5 per rejection_rate unit above 0.20 (e.g. 30% rejection
    rate → confidence = 1.0 − 0.5*(0.30−0.20) = 0.95).
  - Cannot go below 0.0.

Pure Python + numpy — no ORM, no async.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any


import numpy as np

_SETTLING_MINUTES: float = 30.0        # discard first N minutes of first-ever wear
_SPIKE_MULTIPLIER: float = 2.5         # rmssd > N × rolling_median → spike
_SPIKE_WINDOW_HALF: int  = 6           # ±6 neighbours for rolling median
_POPULATION_CEILING: float = 110.0     # ms — hard cap on valid RMSSD
_CONFIDENCE_PENALTY_ABOVE: float = 0.20 # rejection_rate above this triggers penalty
_CONFIDENCE_PENALTY_PER_UNIT: float = 0.5


@dataclass
class FilterResult:
    clean_windows:   list[Any]   # same BackgroundWindowResult objects, just filtered
    rejected_count:  int
    windows_total:   int
    rejection_rate:  float       # rejected / total
    confidence:      float       # 0.0–1.0


def filter_calibration_windows(windows: list[Any]) -> FilterResult:
    """
    Run the 3-pass artifact filter on a list of BackgroundWindowResult objects.

    Parameters
    ----------
    windows : list[BackgroundWindowResult]
        All valid background windows for the user (full history), ordered by
        window_start ascending.  Objects must have attributes:
          .window_start (datetime), .rmssd_ms (float | None)

    Returns
    -------
    FilterResult
    """
    if not windows:
        return FilterResult(
            clean_windows=[], rejected_count=0, windows_total=0,
            rejection_rate=0.0, confidence=0.0,
        )

    # Sort by window_start to guarantee temporal order
    windows = sorted(windows, key=lambda w: w.window_start)
    total = len(windows)

    # ── Pass 1: Settling discard ──────────────────────────────────────────────
    first_ts = windows[0].window_start
    settle_cutoff = first_ts + timedelta(minutes=_SETTLING_MINUTES)
    after_settling = [w for w in windows if w.window_start >= settle_cutoff]

    if not after_settling:
        # All windows fall in settling period — nothing to work with
        return FilterResult(
            clean_windows=[], rejected_count=total, windows_total=total,
            rejection_rate=1.0, confidence=0.0,
        )

    # ── Pass 2: Temporal spike gate ───────────────────────────────────────────
    rmssd_values = np.array(
        [w.rmssd_ms if w.rmssd_ms is not None else 0.0 for w in after_settling],
        dtype=np.float64,
    )
    n = len(rmssd_values)
    after_spike: list[Any] = []
    for i, w in enumerate(after_settling):
        if w.rmssd_ms is None:
            after_spike.append(w)
            continue
        # Gather ±6 neighbours (excluding self)
        lo = max(0, i - _SPIKE_WINDOW_HALF)
        hi = min(n, i + _SPIKE_WINDOW_HALF + 1)
        neighbours = np.concatenate([rmssd_values[lo:i], rmssd_values[i+1:hi]])
        if len(neighbours) == 0:
            after_spike.append(w)
            continue
        rolling_med = float(np.median(neighbours))
        if rolling_med > 0.0 and w.rmssd_ms > _SPIKE_MULTIPLIER * rolling_med:
            continue  # reject — spike
        after_spike.append(w)

    # ── Pass 3: Population ceiling gate ──────────────────────────────────────
    clean = [
        w for w in after_spike
        if w.rmssd_ms is None or w.rmssd_ms <= _POPULATION_CEILING
    ]

    rejected_count = total - len(clean)
    rejection_rate = rejected_count / total if total > 0 else 0.0

    # ── Confidence scoring ────────────────────────────────────────────────────
    confidence = 1.0
    if rejection_rate > _CONFIDENCE_PENALTY_ABOVE:
        penalty = _CONFIDENCE_PENALTY_PER_UNIT * (rejection_rate - _CONFIDENCE_PENALTY_ABOVE)
        confidence = max(0.0, 1.0 - penalty)
    # Additional penalty if very few clean windows remain (< 6)
    if len(clean) < 6:
        confidence = min(confidence, 0.5)

    return FilterResult(
        clean_windows=clean,
        rejected_count=rejected_count,
        windows_total=total,
        rejection_rate=round(rejection_rate, 4),
        confidence=round(confidence, 4),
    )
