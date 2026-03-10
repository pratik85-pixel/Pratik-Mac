"""
config/processing.py

All signal processing parameters.

Design rules:
  - Every value carries a `# downstream:` comment listing dependent modules.
  - Changing a value without reading its downstream comment is a bug.
  - All values must be valid at startup — Pydantic validates at import time.
"""

from pydantic_settings import BaseSettings


class ProcessingConfig(BaseSettings):

    # ── PPI / HRV ─────────────────────────────────────────────────────────────

    # downstream: rsa_analyzer (Lomb-Scargle window), coherence_scorer,
    #             model/coherence_tracker, outcomes/session_outcomes
    RSA_WINDOW_SECONDS: int = 60

    # downstream: ppi_processor (RMSSD rolling window),
    #             model/personal_distributions (distribution granularity)
    RMSSD_WINDOW_SECONDS: int = 60

    # downstream: ppi_processor (outlier rejection before any computation)
    PPI_MIN_MS: int = 300
    PPI_MAX_MS: int = 2000

    # downstream: rsa_analyzer, breath_extractor (RSA method)
    # Respiratory sinus arrhythmia band — centred on 0.1 Hz (6 BPM resonance)
    RSA_FREQ_LOW_HZ: float = 0.08
    RSA_FREQ_HIGH_HZ: float = 0.12

    # downstream: artifact_handler (consecutive bad beats before pause)
    ARTIFACT_MAX_CONSECUTIVE_BEATS: int = 4

    # downstream: ppi_processor (minimum beats required before computing RMSSD)
    RMSSD_MIN_BEATS: int = 10

    # ── PPG ───────────────────────────────────────────────────────────────────

    # downstream: ppg_processor (Perfusion Index window)
    PPG_PI_WINDOW_SECONDS: int = 10

    # downstream: ppg_processor (SpO2 ratio averaging window)
    SPO2_WINDOW_SECONDS: int = 30

    # downstream: ppg_processor, breath_extractor (PAV method)
    PAV_WINDOW_BEATS: int = 20

    # ── ACC / Gyro ────────────────────────────────────────────────────────────

    # downstream: motion_analyzer (restlessness score window)
    RESTLESSNESS_WINDOW_SECONDS: int = 30

    # downstream: motion_analyzer, api/services/session_service
    # HRV degrades after this many minutes of continuous stillness
    SEDENTARY_THRESHOLD_MINUTES: int = 90

    model_config = {"env_prefix": "ZENFLOW_PROCESSING_", "extra": "ignore"}
