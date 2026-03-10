"""
processing/ppi_processor.py

Compute time-domain HRV metrics from a cleaned PPI array.

Metrics:
    RMSSD  — Root Mean Square of Successive Differences (primary NS recovery metric)
    SDNN   — Standard Deviation of NN intervals (overall variability)
    pNN50  — % of successive differences > 50ms (vagal activity marker)
    mean_hr — Mean heart rate in BPM
    mean_ppi — Mean PPI in ms

Notes:
    - Input must be CLEAN PPI (artifacts removed by artifact_handler.filter_ppi_stream).
    - Minimum 20 beats required; shorter windows return None with confidence 0.0.
    - Windowed computation supported for session streaming (process_window).
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass
from typing import Optional

from config import CONFIG


@dataclass
class PPIMetrics:
    """Time-domain HRV metrics computed from a PPI window."""
    rmssd_ms: Optional[float]   # primary metric
    sdnn_ms: Optional[float]
    pnn50_pct: Optional[float]  # 0–100
    mean_hr_bpm: Optional[float]
    mean_ppi_ms: Optional[float]
    n_beats: int
    confidence: float           # 0.0–1.0  (based on n_beats, artifact rate)

    def is_valid(self) -> bool:
        """True if enough beats for reliable metrics."""
        return self.rmssd_ms is not None and self.confidence >= 0.5


# Minimum beats for valid computation
_MIN_BEATS = 20


def compute_ppi_metrics(
    ppi_ms: np.ndarray,
    artifact_rate: float = 0.0,
) -> PPIMetrics:
    """
    Compute time-domain HRV from a clean PPI array.

    Parameters
    ----------
    ppi_ms : np.ndarray
        Clean beat-to-beat PPI values in milliseconds.
    artifact_rate : float
        Fraction of beats that were artifacts (0.0–1.0).
        Used to degrade confidence score.

    Returns
    -------
    PPIMetrics
    """
    n = len(ppi_ms)

    if n < _MIN_BEATS:
        return PPIMetrics(
            rmssd_ms=None, sdnn_ms=None, pnn50_pct=None,
            mean_hr_bpm=None, mean_ppi_ms=None,
            n_beats=n, confidence=0.0,
        )

    diffs = np.diff(ppi_ms)

    rmssd = float(np.sqrt(np.mean(diffs ** 2)))
    sdnn  = float(np.std(ppi_ms, ddof=1))
    pnn50 = float(np.sum(np.abs(diffs) > 50.0) / len(diffs) * 100.0)
    mean_ppi = float(np.mean(ppi_ms))
    mean_hr  = 60000.0 / mean_ppi

    # ── Confidence ────────────────────────────────────────────────────────────
    # Scales up with n_beats, degrades with artifact_rate
    beat_confidence = min(1.0, n / 120.0)        # saturates at 2 min of data
    artifact_penalty = max(0.0, 1.0 - artifact_rate * 3.0)
    confidence = beat_confidence * artifact_penalty

    return PPIMetrics(
        rmssd_ms=rmssd,
        sdnn_ms=sdnn,
        pnn50_pct=pnn50,
        mean_hr_bpm=mean_hr,
        mean_ppi_ms=mean_ppi,
        n_beats=n,
        confidence=round(confidence, 3),
    )


def process_window(
    ppi_ms: np.ndarray,
    timestamps_s: np.ndarray,
    window_start_s: float,
    window_duration_s: Optional[float] = None,
    artifact_rate: float = 0.0,
) -> PPIMetrics:
    """
    Compute HRV metrics for a specific time window within a PPI stream.

    Parameters
    ----------
    ppi_ms : np.ndarray
        Full clean PPI array.
    timestamps_s : np.ndarray
        Beat timestamps in seconds (same length as ppi_ms).
    window_start_s : float
        Start of the window in seconds.
    window_duration_s : float | None
        Duration of window. If None, uses CONFIG.processing.RMSSD_WINDOW_SECONDS.
    artifact_rate : float
        Fraction of artifacts in source data.

    Returns
    -------
    PPIMetrics for the specified window.
    """
    cfg = CONFIG.processing
    duration = window_duration_s or cfg.RMSSD_WINDOW_SECONDS

    mask = (timestamps_s >= window_start_s) & (
        timestamps_s < window_start_s + duration
    )
    window_ppi = ppi_ms[mask]
    return compute_ppi_metrics(window_ppi, artifact_rate=artifact_rate)


def classify_rmssd(
    rmssd_ms: float,
    floor: Optional[float] = None,
    ceiling: Optional[float] = None,
) -> dict:
    """
    Classify an RMSSD value against population norms or personal range.

    Returns
    -------
    dict with keys: label, percentile_population, position_in_personal_range
    """
    # Population norms (approximate, healthy adults 25–50)
    # Source: review of published HRV normative data
    pop_p10, pop_p50, pop_p90 = 20.0, 42.0, 90.0

    if rmssd_ms < pop_p10:
        pop_label = "low"
        pop_pct = max(0.0, rmssd_ms / pop_p10 * 10.0)
    elif rmssd_ms < pop_p50:
        pop_label = "below_average"
        pop_pct = 10.0 + (rmssd_ms - pop_p10) / (pop_p50 - pop_p10) * 40.0
    elif rmssd_ms < pop_p90:
        pop_label = "above_average"
        pop_pct = 50.0 + (rmssd_ms - pop_p50) / (pop_p90 - pop_p50) * 40.0
    else:
        pop_label = "high"
        pop_pct = min(99.0, 90.0 + (rmssd_ms - pop_p90) / 50.0 * 9.0)

    result = {
        "label": pop_label,
        "percentile_population": round(pop_pct, 1),
    }

    # Personal range position (0.0 = at floor, 1.0 = at ceiling)
    if floor is not None and ceiling is not None and ceiling > floor:
        pos = (rmssd_ms - floor) / (ceiling - floor)
        result["position_in_personal_range"] = round(float(np.clip(pos, 0.0, 1.0)), 3)

    return result
