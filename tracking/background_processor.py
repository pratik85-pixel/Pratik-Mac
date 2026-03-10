"""
tracking/background_processor.py

Aggregates raw background-context metrics into 5-minute BackgroundWindow rows.

Role:
    The bridge emits per-beat PPI/ACC/Gyro packets tagged context="background".
    This module collects a WINDOW_MINUTES-wide buffer of those beats and computes
    the window-level metrics that all downstream tracking logic operates on.

    One BackgroundWindowResult per 5-minute period of background wear.

Design rules:
    - Deterministic. No AI.
    - Calls processing/ppi_processor for RMSSD (reuses existing metric computation).
    - Produces confidence score. Windows with confidence < 0.5 are still stored
      but flagged invalid — downstream detectors skip them. Gaps in valid windows
      are handled by wake_detector and daily_summarizer.
    - context tag from bridge: "background" | "sleep". Sleep windows are stored
      with context="sleep" — same table, different context column value.
      Recovery detector handles sleep windows separately.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np

from config import CONFIG
from processing.ppi_processor import compute_ppi_metrics, PPIMetrics


@dataclass
class BackgroundWindowResult:
    """
    One 5-minute aggregated window of background wear data.
    Written directly to the BackgroundWindow DB table.
    """
    user_id:          str
    window_start:     datetime
    window_end:       datetime
    context:          str           # "background" | "sleep"

    # HRV metrics
    rmssd_ms:         Optional[float]    # primary signal for stress/recovery detection
    hr_bpm:           Optional[float]    # mean HR across the window
    lf_hf:            Optional[float]    # LF/HF ratio if computable (needs freq-domain)
    confidence:       float              # 0.0–1.0

    # Motion (for physical vs emotional stress classification)
    acc_mean:         Optional[float]    # mean ACC magnitude across window (g)
    gyro_mean:        Optional[float]    # mean Gyro magnitude across window

    # Data quality
    n_beats:          int
    artifact_rate:    float             # fraction of beats flagged by artifact_handler

    # Derived flag
    is_valid:         bool              # confidence >= 0.5 and rmssd_ms is not None

    def __post_init__(self) -> None:
        self.is_valid = (
            self.rmssd_ms is not None
            and self.confidence >= 0.5
            and self.n_beats >= CONFIG.tracking.BACKGROUND_MIN_BEATS
        )


def aggregate_background_window(
    ppi_ms: np.ndarray,
    ts_start: datetime,
    ts_end: datetime,
    user_id: str,
    context: str = "background",
    artifact_flags: Optional[np.ndarray] = None,
    acc_samples: Optional[np.ndarray] = None,
    gyro_samples: Optional[np.ndarray] = None,
) -> BackgroundWindowResult:
    """
    Compute one BackgroundWindowResult from raw PPI (and optional motion) samples.

    Parameters
    ----------
    ppi_ms : np.ndarray
        Beat-to-beat intervals in milliseconds. Should already be artifact-filtered
        by processing/artifact_handler — pass clean PPI here.
    ts_start : datetime
        Window start timestamp.
    ts_end : datetime
        Window end timestamp.
    user_id : str
        User identifier (UUID string).
    context : str
        "background" | "sleep"
    artifact_flags : np.ndarray, optional
        Boolean array parallel to ppi_ms. True = this beat was flagged as artifact.
        If None, artifact_rate is assumed 0.0.
    acc_samples : np.ndarray, optional
        ACC magnitude samples across the window (g). Used for motion detection.
    gyro_samples : np.ndarray, optional
        Gyro magnitude samples across the window.

    Returns
    -------
    BackgroundWindowResult
    """
    # Compute artifact rate
    if artifact_flags is not None and len(artifact_flags) > 0:
        artifact_rate = float(np.sum(artifact_flags) / len(artifact_flags))
    else:
        artifact_rate = 0.0

    # Clean PPI — remove artifact-flagged beats if flags provided
    if artifact_flags is not None and len(artifact_flags) == len(ppi_ms):
        clean_ppi = ppi_ms[~artifact_flags]
    else:
        clean_ppi = ppi_ms

    # Compute HRV metrics using existing ppi_processor
    metrics: PPIMetrics = compute_ppi_metrics(
        ppi_ms=clean_ppi,
        artifact_rate=artifact_rate,
    )

    # Motion features
    acc_mean: Optional[float] = None
    gyro_mean: Optional[float] = None

    if acc_samples is not None and len(acc_samples) > 0:
        acc_mean = float(np.mean(np.abs(acc_samples)))  # magnitude
    if gyro_samples is not None and len(gyro_samples) > 0:
        gyro_mean = float(np.mean(np.abs(gyro_samples)))

    # Mean HR from mean PPI
    hr_bpm: Optional[float] = None
    if metrics.mean_ppi_ms is not None and metrics.mean_ppi_ms > 0:
        hr_bpm = round(60_000.0 / metrics.mean_ppi_ms, 1)

    return BackgroundWindowResult(
        user_id=user_id,
        window_start=ts_start,
        window_end=ts_end,
        context=context,
        rmssd_ms=metrics.rmssd_ms,
        hr_bpm=hr_bpm,
        lf_hf=None,           # requires frequency-domain analysis — deferred
        confidence=metrics.confidence,
        acc_mean=acc_mean,
        gyro_mean=gyro_mean,
        n_beats=metrics.n_beats,
        artifact_rate=artifact_rate,
        is_valid=False,        # set by __post_init__
    )


def has_motion(window: BackgroundWindowResult) -> bool:
    """
    Return True if ACC mean suggests active movement.
    Used by stress_detector to classify physical vs emotional stress.
    """
    if window.acc_mean is None:
        return False
    return window.acc_mean > CONFIG.tracking.MOTION_ACTIVE_THRESHOLD
