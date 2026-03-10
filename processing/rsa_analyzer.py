"""
processing/rsa_analyzer.py

Compute RSA (Respiratory Sinus Arrhythmia) power using Lomb-Scargle periodogram.

Why Lomb-Scargle:
    PPI from Polar Verity Sense is event-driven (irregular timestamps).
    Standard FFT requires uniformly sampled data. Re-sampling PPI to a
    uniform grid introduces interpolation artefacts. Lomb-Scargle is designed
    for unevenly sampled series — no resampling needed.

RSA interpretation:
    RSA power in 0.08–0.12 Hz (6–7.5 BPM) reflects respiratory amplitude
    modulation of cardiac vagal output. This is the physiological substrate
    of "HRV coherence" during resonance breathing at 0.1 Hz (6 BPM).

    Higher RSA_POWER → stronger vagal activity → better recovery capacity.
    RSA_PEAK_FREQUENCY near 0.1 Hz → user is near resonance breathing rate.
"""

from __future__ import annotations

import numpy as np
from scipy.signal import lombscargle
from dataclasses import dataclass
from typing import Optional

from config import CONFIG


@dataclass
class RSAResult:
    """RSA analysis output for one time window."""
    rsa_power: Optional[float]          # Power in RSA band (0.08–0.12 Hz), arbitrary units
    rsa_peak_freq_hz: Optional[float]   # Dominant frequency in RSA band
    total_hrv_power: Optional[float]    # Total power in 0.04–0.4 Hz (LF + HF)
    lf_power: Optional[float]           # Low-frequency power (0.04–0.15 Hz)
    hf_power: Optional[float]           # High-frequency power (0.15–0.4 Hz)
    lf_hf_ratio: Optional[float]        # LF/HF — sympathovagal balance index
    n_beats: int
    confidence: float                   # 0.0–1.0

    def is_valid(self) -> bool:
        return self.rsa_power is not None and self.confidence >= 0.5


# ── Frequency bands (Hz) ──────────────────────────────────────────────────────
_TOTAL_LOW_HZ  = 0.04
_TOTAL_HIGH_HZ = 0.40
_LF_LOW_HZ     = 0.04
_LF_HIGH_HZ    = 0.15
_HF_LOW_HZ     = 0.15
_HF_HIGH_HZ    = 0.40
_N_FREQ_POINTS = 2000   # resolution of periodogram

# Minimum beats for frequency analysis (need ~60s at HR 60bpm = 60 beats)
_MIN_BEATS = 30


def compute_rsa(
    ppi_ms: np.ndarray,
    timestamps_s: np.ndarray,
    artifact_rate: float = 0.0,
) -> RSAResult:
    """
    Compute RSA and spectral HRV from a clean PPI stream.

    Parameters
    ----------
    ppi_ms : np.ndarray
        Clean PPI values in milliseconds.
    timestamps_s : np.ndarray
        Beat timestamps in seconds (same length as ppi_ms).
    artifact_rate : float
        Fraction of artifacts in source (for confidence degradation).

    Returns
    -------
    RSAResult
    """
    n = len(ppi_ms)
    cfg = CONFIG.processing

    if n < _MIN_BEATS:
        return RSAResult(
            rsa_power=None, rsa_peak_freq_hz=None,
            total_hrv_power=None, lf_power=None, hf_power=None,
            lf_hf_ratio=None, n_beats=n, confidence=0.0
        )

    # Centre the PPI series around zero for Lomb-Scargle
    ppi_centred = ppi_ms - np.mean(ppi_ms)

    # ── Compute Lomb-Scargle periodogram ─────────────────────────────────────
    freqs_hz = np.linspace(_TOTAL_LOW_HZ, _TOTAL_HIGH_HZ, _N_FREQ_POINTS)
    ang_freqs = 2.0 * np.pi * freqs_hz

    # lombscargle returns power normalised so that a pure sine of amplitude A
    # produces a peak at A^2 / 2 when normalize=False.
    # We use normalize=True (unit variance normalisation).
    pgram = lombscargle(
        timestamps_s.astype(np.float64),
        ppi_centred.astype(np.float64),
        ang_freqs,
        normalize=True,
    )

    # ── Band power (integrate periodogram over band) ──────────────────────────
    freq_step = freqs_hz[1] - freqs_hz[0]

    def band_power(low_hz: float, high_hz: float) -> float:
        mask = (freqs_hz >= low_hz) & (freqs_hz < high_hz)
        return float(np.trapezoid(pgram[mask], freqs_hz[mask])) if mask.any() else 0.0

    # RSA band (from config)
    rsa_mask = (freqs_hz >= cfg.RSA_FREQ_LOW_HZ) & (freqs_hz < cfg.RSA_FREQ_HIGH_HZ)
    if not rsa_mask.any():
        return RSAResult(
            rsa_power=None, rsa_peak_freq_hz=None,
            total_hrv_power=None, lf_power=None, hf_power=None,
            lf_hf_ratio=None, n_beats=n, confidence=0.0
        )

    rsa_power    = band_power(cfg.RSA_FREQ_LOW_HZ, cfg.RSA_FREQ_HIGH_HZ)
    lf_power     = band_power(_LF_LOW_HZ, _LF_HIGH_HZ)
    hf_power     = band_power(_HF_LOW_HZ, _HF_HIGH_HZ)
    total_power  = band_power(_TOTAL_LOW_HZ, _TOTAL_HIGH_HZ)
    lf_hf_ratio  = lf_power / hf_power if hf_power > 1e-10 else None

    # Peak frequency within RSA band
    rsa_pgram   = pgram[rsa_mask]
    rsa_freqs   = freqs_hz[rsa_mask]
    rsa_peak_hz = float(rsa_freqs[np.argmax(rsa_pgram)])

    # ── Confidence ────────────────────────────────────────────────────────────
    # Needs min 60s of decent data; degrades with artifacts
    duration_s = timestamps_s[-1] - timestamps_s[0] if len(timestamps_s) > 1 else 0.0
    duration_factor = min(1.0, duration_s / cfg.RSA_WINDOW_SECONDS)
    artifact_penalty = max(0.0, 1.0 - artifact_rate * 4.0)
    confidence = duration_factor * artifact_penalty

    return RSAResult(
        rsa_power=round(rsa_power, 6),
        rsa_peak_freq_hz=round(rsa_peak_hz, 4),
        total_hrv_power=round(total_power, 6),
        lf_power=round(lf_power, 6),
        hf_power=round(hf_power, 6),
        lf_hf_ratio=round(lf_hf_ratio, 3) if lf_hf_ratio else None,
        n_beats=n,
        confidence=round(confidence, 3),
    )


def compute_windowed_rsa(
    ppi_ms: np.ndarray,
    timestamps_s: np.ndarray,
    window_duration_s: Optional[float] = None,
    step_s: float = 10.0,
    artifact_rate: float = 0.0,
) -> list[dict]:
    """
    Compute RSA in sliding windows across a session.

    Returns
    -------
    list of dicts with keys: window_start_s, rsa_power, rsa_peak_freq_hz, confidence
    """
    cfg = CONFIG.processing
    win = window_duration_s or float(cfg.RSA_WINDOW_SECONDS)

    if len(timestamps_s) == 0:
        return []

    total_duration = timestamps_s[-1] - timestamps_s[0]
    results = []

    t = timestamps_s[0]
    while t + win <= timestamps_s[-1] + step_s:
        mask = (timestamps_s >= t) & (timestamps_s < t + win)
        w_ppi = ppi_ms[mask]
        w_ts  = timestamps_s[mask]

        result = compute_rsa(w_ppi, w_ts, artifact_rate=artifact_rate)
        results.append({
            "window_start_s":   round(float(t - timestamps_s[0]), 1),
            "rsa_power":        result.rsa_power,
            "rsa_peak_freq_hz": result.rsa_peak_freq_hz,
            "confidence":       result.confidence,
        })
        t += step_s

    return results
