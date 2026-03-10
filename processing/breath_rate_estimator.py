"""
processing/breath_rate_estimator.py

Estimate current breathing rate (BPM) from raw PPI data.

Context
-------
The OG app used an accelerometer to directly measure chest/belly movement and
derive instantaneous breath period. Verity has no accelerometer. Instead, we
infer breathing rate from the RSA oscillation embedded in the PPI series:
cardiac vagal tone is modulated by respiration, so the dominant oscillation
in a bandpass-filtered PPI series is the breath cycle.

Algorithm
---------
1. Bandpass filter PPI to the breathing range: 0.07–0.40 Hz (4–24 BPM)
2. Detect local maxima (inspiration peaks — PPI shortens on inhale)
3. Compute period between consecutive peaks → BPM = 60 / period_s
4. Median over all detected cycles for stability

Update rate vs accelerometer
-----------------------------
- Accelerometer: ~2–5 s update (direct mechanical signal)
- This estimator: ~5–15 s (at 6 BPM = one peak every 10 s)

Fast enough for step-down gate decisions, which are buffered by Gate B's
stability window requirement.

Limitation
----------
Stage 0 users with weak RSA amplitude may produce noisy estimates. Mitigated
by `ring_entrainment` being the first practice (no Gate A) — the user builds
enough RSA quality before step-down gates activate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy.signal import butter, filtfilt, find_peaks


# ── Constants ─────────────────────────────────────────────────────────────────

# Breathing band: 4–24 BPM → 0.067–0.40 Hz
_BREATH_LOW_HZ  = 0.07
_BREATH_HIGH_HZ = 0.40

# Minimum beats for a reliable estimate
_MIN_BEATS = 15

# Minimum detectable peak-to-peak interval (seconds) — caps BPM at 24
_MIN_PERIOD_S = 2.5   # 24 BPM

# Maximum detectable peak-to-peak interval (seconds) — floors BPM at 3
_MAX_PERIOD_S = 20.0  # 3 BPM

# Minimum number of complete breath cycles required for a valid estimate
_MIN_CYCLES = 2

# BPM bounds for sanity clamping
_BPM_MIN = 3.0
_BPM_MAX = 24.0


# ── Output type ───────────────────────────────────────────────────────────────

@dataclass
class BreathRateEstimate:
    """
    Current breathing rate estimated from PPI oscillation.

    Fields
    ------
    bpm : float | None
        Estimated breathing rate in breaths per minute.
        None if insufficient data or signal quality too low.
    confidence : float
        0.0–1.0. Driven by number of detected cycles and signal clarity.
    n_cycles : int
        Number of complete breath cycles detected.
    method : str
        "peak_detection" | "insufficient_data"
    """
    bpm:        Optional[float]
    confidence: float
    n_cycles:   int
    method:     str = "peak_detection"

    def is_valid(self) -> bool:
        """True if estimate is usable for Gate A comparison."""
        return self.bpm is not None and self.confidence >= 0.4


# ── Public API ─────────────────────────────────────────────────────────────────

def estimate_breath_rate(
    ppi_ms: np.ndarray,
    timestamps_s: np.ndarray,
) -> BreathRateEstimate:
    """
    Estimate current breathing rate from a recent PPI window.

    Parameters
    ----------
    ppi_ms : np.ndarray
        Clean PPI values in milliseconds, chronological order.
        Typically 20–60 s of data (15–80 beats at resting HR).
    timestamps_s : np.ndarray
        Beat timestamps in seconds, same length as ppi_ms.
        Must be strictly increasing.

    Returns
    -------
    BreathRateEstimate
        bpm=None if fewer than _MIN_BEATS or fewer than _MIN_CYCLES detected.
    """
    ppi_ms     = np.asarray(ppi_ms,     dtype=float)
    timestamps_s = np.asarray(timestamps_s, dtype=float)

    if len(ppi_ms) < _MIN_BEATS or len(timestamps_s) < _MIN_BEATS:
        return BreathRateEstimate(
            bpm=None, confidence=0.0, n_cycles=0,
            method="insufficient_data",
        )

    if len(ppi_ms) != len(timestamps_s):
        return BreathRateEstimate(
            bpm=None, confidence=0.0, n_cycles=0,
            method="insufficient_data",
        )

    # ── Step 1: interpolate to uniform grid for filtering ─────────────────────
    # Breathing oscillation is slow — 4 Hz sample rate is more than enough
    sample_rate_hz = 4.0
    t_uniform = np.arange(timestamps_s[0], timestamps_s[-1], 1.0 / sample_rate_hz)

    if len(t_uniform) < int(sample_rate_hz * 5):
        # Less than 5 seconds of data
        return BreathRateEstimate(
            bpm=None, confidence=0.0, n_cycles=0,
            method="insufficient_data",
        )

    ppi_uniform = np.interp(t_uniform, timestamps_s, ppi_ms)

    # ── Step 2: bandpass filter to breathing range ────────────────────────────
    nyquist = sample_rate_hz / 2.0
    low  = _BREATH_LOW_HZ  / nyquist
    high = _BREATH_HIGH_HZ / nyquist

    # Clamp to valid range (filtfilt requires 0 < Wn < 1)
    low  = float(np.clip(low,  1e-4, 0.99))
    high = float(np.clip(high, 1e-4, 0.99))

    if low >= high:
        return BreathRateEstimate(
            bpm=None, confidence=0.0, n_cycles=0,
            method="insufficient_data",
        )

    try:
        b, a = butter(2, [low, high], btype="band")
        filtered = filtfilt(b, a, ppi_uniform)
    except Exception:
        return BreathRateEstimate(
            bpm=None, confidence=0.0, n_cycles=0,
            method="insufficient_data",
        )

    # ── Step 3: detect peaks (inspiration = PPI shortens = local minimum in PPI)
    # We invert for find_peaks since inspiratory RSA causes PPI shortening
    inverted = -filtered

    # Minimum distance between peaks: MIN_PERIOD_S seconds
    min_distance = max(1, int(_MIN_PERIOD_S * sample_rate_hz))

    peaks, properties = find_peaks(
        inverted,
        distance=min_distance,
        prominence=np.std(filtered) * 0.3,   # ignore tiny oscillations
    )

    if len(peaks) < _MIN_CYCLES + 1:
        # Not enough peaks for _MIN_CYCLES complete cycles
        return BreathRateEstimate(
            bpm=None, confidence=0.0, n_cycles=len(peaks),
            method="peak_detection",
        )

    # ── Step 4: compute period between consecutive peaks ─────────────────────
    peak_times = t_uniform[peaks]
    periods_s  = np.diff(peak_times)

    # Filter out implausible periods
    valid_mask = (periods_s >= _MIN_PERIOD_S) & (periods_s <= _MAX_PERIOD_S)
    valid_periods = periods_s[valid_mask]

    if len(valid_periods) < _MIN_CYCLES:
        return BreathRateEstimate(
            bpm=None, confidence=0.0, n_cycles=int(valid_mask.sum()),
            method="peak_detection",
        )

    # ── Step 5: median BPM + confidence ──────────────────────────────────────
    median_period = float(np.median(valid_periods))
    bpm = float(np.clip(60.0 / median_period, _BPM_MIN, _BPM_MAX))

    # Confidence: based on cycle count and period consistency
    n_cycles = len(valid_periods)
    cycle_score = min(1.0, n_cycles / 6.0)   # full confidence at 6+ cycles

    # Coefficient of variation of periods (lower = more consistent)
    if len(valid_periods) > 1:
        cv = float(np.std(valid_periods) / (np.mean(valid_periods) + 1e-10))
        consistency_score = float(np.clip(1.0 - cv * 2.0, 0.0, 1.0))
    else:
        consistency_score = 0.5

    confidence = round((cycle_score * 0.6) + (consistency_score * 0.4), 3)

    return BreathRateEstimate(
        bpm=round(bpm, 2),
        confidence=confidence,
        n_cycles=n_cycles,
        method="peak_detection",
    )


# ── Gate A helper ─────────────────────────────────────────────────────────────

def gate_a_passes(
    estimate: BreathRateEstimate,
    target_bpm: float,
    tolerance_bpm: float = 1.5,
) -> bool:
    """
    Gate A: is the user's detected breathing rate within tolerance of target?

    Parameters
    ----------
    estimate : BreathRateEstimate
        Output of estimate_breath_rate().
    target_bpm : float
        Current step-down target BPM.
    tolerance_bpm : float
        Acceptable deviation. Default 1.5 BPM (from OG app design).

    Returns
    -------
    bool
        False if estimate is not valid.
    """
    if not estimate.is_valid():
        return False
    return abs(estimate.bpm - target_bpm) <= tolerance_bpm
