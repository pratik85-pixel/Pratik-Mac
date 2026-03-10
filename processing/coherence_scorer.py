"""
processing/coherence_scorer.py

Compute HRV coherence score from RSA power.

Coherence definition (ZenFlow):
    coherence = RSA_power / total_HRV_power

    Where:
      RSA_power   = spectral power in 0.08–0.12 Hz band (Lomb-Scargle)
      total_power = spectral power in 0.04–0.4 Hz band

    This is the same definition used by HeartMath for their "coherence ratio"
    and is the industry standard for biofeedback coherence training.

    Result: 0.0–1.0
    - 0.0 = all HRV power scattered across frequencies (disordered)
    - 1.0 = all HRV power concentrated in RSA band (perfectly ordered)

    In practice:
    - < 0.40 = Zone 1 (low coherence)
    - 0.40–0.60 = Zone 2
    - 0.60–0.80 = Zone 3
    - ≥ 0.80 = Zone 4 (high coherence — Hardmode territory)

Zone assignment is controlled by config/scoring.py (ZONE_*_MIN thresholds).
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass
from typing import Optional

from config import CONFIG
from processing.rsa_analyzer import RSAResult, compute_rsa


@dataclass
class CoherenceResult:
    """Coherence score for one time window."""
    coherence: Optional[float]    # 0.0–1.0
    zone: Optional[int]           # 1–4 (None if insufficient data)
    rsa_power: Optional[float]
    total_power: Optional[float]
    confidence: float

    def is_valid(self) -> bool:
        return self.coherence is not None and self.confidence >= 0.5

    def zone_label(self) -> str:
        labels = {1: "scattered", 2: "building", 3: "coherent", 4: "high_coherence"}
        return labels.get(self.zone, "unknown") if self.zone else "unknown"


def compute_coherence(
    ppi_ms: np.ndarray,
    timestamps_s: np.ndarray,
    artifact_rate: float = 0.0,
) -> CoherenceResult:
    """
    Compute coherence from a clean PPI window.

    Parameters
    ----------
    ppi_ms : np.ndarray
        Clean PPI values in milliseconds.
    timestamps_s : np.ndarray
        Beat timestamps in seconds.
    artifact_rate : float
        Fraction of artifacts in source.

    Returns
    -------
    CoherenceResult
    """
    rsa_result = compute_rsa(ppi_ms, timestamps_s, artifact_rate=artifact_rate)

    if not rsa_result.is_valid():
        return CoherenceResult(
            coherence=None, zone=None,
            rsa_power=None, total_power=None,
            confidence=rsa_result.confidence,
        )

    rsa_power   = rsa_result.rsa_power or 0.0
    total_power = rsa_result.total_hrv_power or 0.0

    if total_power < 1e-10:
        return CoherenceResult(
            coherence=0.0, zone=1,
            rsa_power=rsa_power, total_power=total_power,
            confidence=rsa_result.confidence,
        )

    coherence = float(np.clip(rsa_power / total_power, 0.0, 1.0))
    zone = _assign_zone(coherence)

    return CoherenceResult(
        coherence=round(coherence, 4),
        zone=zone,
        rsa_power=rsa_result.rsa_power,
        total_power=rsa_result.total_hrv_power,
        confidence=rsa_result.confidence,
    )


def _assign_zone(coherence: float) -> int:
    """
    Map coherence value to zone (1–4) using ScoringConfig thresholds.
    """
    sc = CONFIG.scoring
    if coherence >= sc.ZONE_4_MIN:
        return 4
    if coherence >= sc.ZONE_3_MIN:
        return 3
    if coherence >= sc.ZONE_2_MIN:
        return 2
    return 1


def compute_session_coherence_avg(
    window_coherences: list[CoherenceResult],
    min_confidence: float = 0.5,
) -> Optional[float]:
    """
    Compute session-average coherence from a list of window results.

    Only windows above min_confidence threshold are included.
    Returns None if no valid windows.
    """
    valid = [
        w.coherence for w in window_coherences
        if w.coherence is not None and w.confidence >= min_confidence
    ]
    if not valid:
        return None
    return round(float(np.mean(valid)), 4)


def compute_zone_time_seconds(
    window_coherences: list[CoherenceResult],
    window_duration_s: float = 10.0,
    min_confidence: float = 0.5,
) -> dict[int, float]:
    """
    Compute seconds spent in each zone during a session.

    Parameters
    ----------
    window_coherences : list[CoherenceResult]
    window_duration_s : float
        Duration of each window in seconds.
    min_confidence : float

    Returns
    -------
    dict mapping zone (1–4) → total seconds
    """
    zone_seconds: dict[int, float] = {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0}
    for w in window_coherences:
        if w.zone is not None and w.confidence >= min_confidence:
            zone_seconds[w.zone] = zone_seconds.get(w.zone, 0.0) + window_duration_s
    return zone_seconds


def compute_session_score(
    window_coherences: list[CoherenceResult],
    window_duration_s: float = 10.0,
    min_confidence: float = 0.5,
) -> Optional[float]:
    """
    Compute a 0–100 session score from zone time distribution.

    Score = weighted average of zone fraction × zone weight
    Zone weights are defined in ScoringConfig.

    Returns None if no valid data.
    """
    sc = CONFIG.scoring
    zone_seconds = compute_zone_time_seconds(
        window_coherences, window_duration_s, min_confidence
    )
    total_seconds = sum(zone_seconds.values())
    if total_seconds < 1.0:
        return None

    zone_weights = {
        1: sc.ZONE_1_WEIGHT,
        2: sc.ZONE_2_WEIGHT,
        3: sc.ZONE_3_WEIGHT,
        4: sc.ZONE_4_WEIGHT,
    }
    weighted_sum = sum(
        (zone_seconds[z] / total_seconds) * zone_weights[z]
        for z in range(1, 5)
    )

    # Normalise to 0–100
    max_possible_weight = max(zone_weights.values())
    score = (weighted_sum / max_possible_weight) * 100.0
    return round(float(np.clip(score, 0.0, 100.0)), 1)
