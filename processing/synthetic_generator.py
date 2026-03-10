"""
processing/synthetic_generator.py

Generates realistic synthetic PPI (peak-to-peak interval) streams for testing
processing algorithms before hardware is available.

Usage:
    from processing.synthetic_generator import SyntheticPPIGenerator, PersonaType

    gen = SyntheticPPIGenerator(persona=PersonaType.WIRE)
    ppi_ms, timestamps = gen.generate(duration_seconds=300)

Personas match the archetype system:
    WIRE          — chronic sympathetic dominance, low HRV, slow recovery
    RUMINATOR     — normal HRV but disrupted at night, high within-session variance
    SLOW_BURNER   — HRV degrades monotonically through a simulated week
    RESPONDER     — high HRV, fast coherence trainability, clean RSA signal
    BASELINE      — neutral — used for algorithm unit tests

Signal model:
    PPI(t) = mean_interval + RSA_amplitude × sin(2π × RSA_freq × t)
           + noise ε ~ N(0, jitter_std)
           + occasional artifact bursts
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class PersonaType(str, Enum):
    WIRE        = "wire"
    RUMINATOR   = "ruminator"
    SLOW_BURNER = "slow_burner"
    RESPONDER   = "responder"
    BASELINE    = "baseline"


@dataclass
class PersonaParams:
    """Physiological parameters defining a persona's PPI signal."""

    # Base heart rate → mean PPI (ms)
    # HR = 60000 / mean_ppi_ms
    mean_ppi_ms: float

    # RSA oscillation amplitude (ms) — how much PPI varies with breathing
    # Higher = more vagal tone = higher HRV
    rsa_amplitude_ms: float

    # RSA frequency (Hz) — should be 0.1 Hz (6 BPM) for resonance breathing
    rsa_freq_hz: float = 0.1

    # Beat-to-beat jitter (Gaussian noise std, ms)
    jitter_std_ms: float = 8.0

    # Probability of an artifact beat per beat
    artifact_prob: float = 0.01

    # Artifact magnitude (ms shift — simulates motion)
    artifact_magnitude_ms: float = 150.0


PERSONA_PARAMS: dict[PersonaType, PersonaParams] = {
    PersonaType.WIRE: PersonaParams(
        mean_ppi_ms=780.0,      # HR ~77 bpm — chronically elevated
        rsa_amplitude_ms=25.0,  # Low vagal tone — small RSA oscillation
        jitter_std_ms=10.0,     # Higher noise floor
        artifact_prob=0.015,
    ),
    PersonaType.RUMINATOR: PersonaParams(
        mean_ppi_ms=870.0,      # HR ~69 bpm — normal resting
        rsa_amplitude_ms=45.0,  # Moderate RSA
        jitter_std_ms=9.0,
        artifact_prob=0.012,
    ),
    PersonaType.SLOW_BURNER: PersonaParams(
        mean_ppi_ms=830.0,      # HR ~72 bpm
        rsa_amplitude_ms=35.0,  # Moderate RSA — degrades across a simulated week
        jitter_std_ms=9.0,
        artifact_prob=0.010,
    ),
    PersonaType.RESPONDER: PersonaParams(
        mean_ppi_ms=950.0,      # HR ~63 bpm — good cardiovascular health
        rsa_amplitude_ms=80.0,  # High vagal tone — large RSA oscillation
        jitter_std_ms=6.0,      # Cleaner signal
        artifact_prob=0.005,
    ),
    PersonaType.BASELINE: PersonaParams(
        mean_ppi_ms=860.0,      # HR ~70 bpm — neutral reference
        rsa_amplitude_ms=50.0,  # Clean RSA — ideal for algorithm unit tests
        jitter_std_ms=7.0,
        artifact_prob=0.0,      # No artifacts in baseline — deterministic tests
    ),
}


class SyntheticPPIGenerator:
    """
    Generate a synthetic PPI stream with a realistic RSA signal.

    Parameters
    ----------
    persona : PersonaType
        Which archetype profile to simulate.
    seed : int | None
        Random seed for reproducibility. None = random each call.
    """

    def __init__(
        self,
        persona: PersonaType = PersonaType.BASELINE,
        seed: Optional[int] = 42,
    ) -> None:
        self.params = PERSONA_PARAMS[persona]
        self.persona = persona
        self.rng = np.random.default_rng(seed)

    def generate(
        self,
        duration_seconds: float = 300.0,
        breathing_rate_hz: float = 0.1,
        include_artifacts: bool = True,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Generate a PPI stream.

        Parameters
        ----------
        duration_seconds : float
            Total duration of the simulated recording.
        breathing_rate_hz : float
            Override RSA frequency (default 0.1 Hz = 6 BPM resonance).
        include_artifacts : bool
            Whether to inject artifact beats (motion simulation).

        Returns
        -------
        ppi_ms : np.ndarray
            Array of PPI values in milliseconds.
        timestamps_s : np.ndarray
            Cumulative timestamps in seconds (time of each beat).
        """
        params = self.params
        rsa_freq = breathing_rate_hz

        # Estimate number of beats
        mean_hr = 60000.0 / params.mean_ppi_ms
        n_beats = int(duration_seconds * mean_hr / 60.0) + 10

        # --- Build beat timestamps ---
        # Start with mean interval, then add RSA oscillation and noise
        beat_times = np.zeros(n_beats)
        current_time = 0.0

        for i in range(n_beats):
            # RSA oscillation — sinusoidal modulation at breathing frequency
            rsa = params.rsa_amplitude_ms * np.sin(
                2.0 * np.pi * rsa_freq * current_time
            )

            # Gaussian jitter (autonomic noise)
            jitter = self.rng.normal(0.0, params.jitter_std_ms)

            # Compute this PPI
            ppi = params.mean_ppi_ms + rsa + jitter

            # Clamp to physiologically valid range
            ppi = float(np.clip(ppi, 300.0, 2000.0))

            beat_times[i] = current_time
            current_time += ppi / 1000.0  # advance in seconds

        # Trim to duration
        mask = beat_times < duration_seconds
        beat_times = beat_times[mask]
        n_beats = len(beat_times)

        # Reconstruct PPI from timestamps
        ppi_ms = np.diff(beat_times) * 1000.0

        # Beat times are the time of each beat (excluding first)
        timestamps_s = beat_times[1:]

        # --- Inject artifacts ---
        if include_artifacts and params.artifact_prob > 0:
            artifact_mask = self.rng.random(n_beats - 1) < params.artifact_prob
            # Artifact: either very short or very long interval
            artifact_direction = self.rng.choice([-1, 1], size=artifact_mask.sum())
            ppi_ms[artifact_mask] += artifact_direction * params.artifact_magnitude_ms
            ppi_ms = np.clip(ppi_ms, 300.0, 2000.0)

        return ppi_ms.astype(np.float64), timestamps_s.astype(np.float64)

    def generate_session_stream(
        self,
        duration_seconds: float = 300.0,
        breathing_rate_hz: float = 0.1,
    ) -> list[dict]:
        """
        Generate a stream of PPI packets matching the WebSocket bridge format.

        Returns
        -------
        list of dicts with keys: stream, context, ts, value, artifact
        """
        ppi_ms, timestamps_s = self.generate(
            duration_seconds=duration_seconds,
            breathing_rate_hz=breathing_rate_hz,
            include_artifacts=True,
        )

        packets = []
        for ts, val in zip(timestamps_s, ppi_ms):
            is_artifact = val < 350.0 or val > 1800.0
            packets.append({
                "stream":   "ppi",
                "context":  "session",
                "ts":       float(ts),
                "value":    float(val),
                "artifact": bool(is_artifact),
            })
        return packets


def generate_multi_persona_dataset(
    duration_seconds: float = 300.0,
    seed: int = 42,
) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """
    Generate PPI streams for all personas. Useful for batch testing.

    Returns
    -------
    dict mapping persona name → (ppi_ms, timestamps_s)
    """
    results = {}
    for persona in PersonaType:
        gen = SyntheticPPIGenerator(persona=persona, seed=seed)
        ppi_ms, ts = gen.generate(duration_seconds=duration_seconds)
        results[persona.value] = (ppi_ms, ts)
    return results


if __name__ == "__main__":
    # Quick sanity check — run this file directly
    from rich import print as rprint

    for persona in PersonaType:
        gen = SyntheticPPIGenerator(persona=persona, seed=42)
        ppi, ts = gen.generate(duration_seconds=60.0)

        mean_hr = 60000.0 / np.mean(ppi)
        rmssd = np.sqrt(np.mean(np.diff(ppi) ** 2))

        rprint(
            f"[bold]{persona.value:14s}[/bold]  "
            f"n={len(ppi):4d}  "
            f"mean_ppi={np.mean(ppi):.1f}ms  "
            f"HR={mean_hr:.1f}bpm  "
            f"RMSSD={rmssd:.1f}ms"
        )
