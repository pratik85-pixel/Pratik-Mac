"""
processing/artifact_handler.py

Artifact detection and handling for PPI (and PPG) streams.

Rules:
  - Never silently remove artefacts — always flag them.
  - The caller (processor) decides whether to skip, interpolate, or hold-last-good.
  - Consecutive artifact runs beyond ARTIFACT_MAX_CONSECUTIVE_BEATS → pause flag.

Artifact types detected:
  - Range artifact: PPI outside [PPI_MIN_MS, PPI_MAX_MS]
  - Jump artifact:  consecutive PPI change > JUMP_THRESHOLD_PCT of previous beat
  - Ectopic beat:   PPI deviates > N std from a local rolling mean
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass
from typing import Sequence

from config import CONFIG


@dataclass
class ArtifactResult:
    """Result of artifact detection for a single PPI value."""
    is_artifact: bool
    reason: str        # "" if clean, else "range" | "jump" | "ectopic"
    confidence: float  # 1.0 = certainly artifact, 0.0 = certainly clean


# Jump threshold: if PPI changes by more than this fraction from previous beat → artifact
_JUMP_THRESHOLD_PCT = 0.25

# Ectopic threshold: deviation from rolling mean in standard deviations
_ECTOPIC_Z_THRESHOLD = 3.0

# Rolling window for ectopic detection (beats)
_ECTOPIC_WINDOW = 20


def detect_artifact(
    ppi_ms: float,
    prev_ppi_ms: float | None = None,
    recent_ppis: Sequence[float] | None = None,
) -> ArtifactResult:
    """
    Check a single PPI value for artifact.

    Parameters
    ----------
    ppi_ms : float
        The PPI value to check (milliseconds).
    prev_ppi_ms : float | None
        The immediately preceding PPI value (for jump detection).
    recent_ppis : sequence of float | None
        Recent clean PPI values for ectopic detection (rolling window).

    Returns
    -------
    ArtifactResult
    """
    cfg = CONFIG.processing

    # ── Range check ──────────────────────────────────────────────────────────
    if ppi_ms < cfg.PPI_MIN_MS or ppi_ms > cfg.PPI_MAX_MS:
        return ArtifactResult(is_artifact=True, reason="range", confidence=1.0)

    # ── Jump check ────────────────────────────────────────────────────────────
    if prev_ppi_ms is not None and prev_ppi_ms > 0:
        change_pct = abs(ppi_ms - prev_ppi_ms) / prev_ppi_ms
        if change_pct > _JUMP_THRESHOLD_PCT:
            confidence = min(1.0, change_pct / (_JUMP_THRESHOLD_PCT * 2))
            return ArtifactResult(
                is_artifact=True, reason="jump", confidence=confidence
            )

    # ── Ectopic check ─────────────────────────────────────────────────────────
    if recent_ppis is not None and len(recent_ppis) >= 5:
        window = list(recent_ppis[-_ECTOPIC_WINDOW:])
        mean = float(np.mean(window))
        std  = float(np.std(window))
        if std > 0:
            z = abs(ppi_ms - mean) / std
            if z > _ECTOPIC_Z_THRESHOLD:
                confidence = min(1.0, z / (_ECTOPIC_Z_THRESHOLD * 2))
                return ArtifactResult(
                    is_artifact=True, reason="ectopic", confidence=confidence
                )

    return ArtifactResult(is_artifact=False, reason="", confidence=0.0)


def filter_ppi_stream(
    ppi_ms: np.ndarray,
    timestamps_s: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Filter a PPI array, flagging artifacts.

    Parameters
    ----------
    ppi_ms : np.ndarray
        Raw PPI values (ms).
    timestamps_s : np.ndarray
        Beat timestamps (seconds), same length as ppi_ms.

    Returns
    -------
    clean_ppi : np.ndarray     — artifact-free PPI values
    clean_ts  : np.ndarray     — corresponding timestamps
    artifact_flags : np.ndarray (bool) — True where artifact was detected, same len as input
    """
    n = len(ppi_ms)
    flags = np.zeros(n, dtype=bool)
    recent: list[float] = []

    for i in range(n):
        prev = ppi_ms[i - 1] if i > 0 else None
        result = detect_artifact(ppi_ms[i], prev_ppi_ms=prev, recent_ppis=recent)
        flags[i] = result.is_artifact
        if not result.is_artifact:
            recent.append(float(ppi_ms[i]))
            if len(recent) > _ECTOPIC_WINDOW:
                recent.pop(0)

    clean_mask = ~flags
    return ppi_ms[clean_mask], timestamps_s[clean_mask], flags


def check_consecutive_artifacts(flags: np.ndarray) -> bool:
    """
    Return True if any run of consecutive artifacts exceeds the configured limit.
    Used to decide whether to pause computation (hold-last-good) during a session.
    """
    max_consecutive = CONFIG.processing.ARTIFACT_MAX_CONSECUTIVE_BEATS
    run = 0
    for f in flags:
        if f:
            run += 1
            if run >= max_consecutive:
                return True
        else:
            run = 0
    return False
