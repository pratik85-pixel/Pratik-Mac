"""
config/features.py

Feature flags — control experimental or in-progress functionality.

Rules:
  - Off by default = safe for production.
  - Never use commented-out code to disable features. Use flags.
  - Flags are config — they can be overridden per environment in .env files.
"""

from pydantic_settings import BaseSettings


class FeatureFlags(BaseSettings):

    # Breath extraction from PPG Pulse Amplitude Variation
    # OFF until 3-channel PPG pipeline is validated on real Verity data
    ENABLE_PAV_BREATH: bool = False

    # SpO2 trend in-session
    # OFF until 3-channel PPG ratio calibration is validated
    ENABLE_SPO2_TREND: bool = False

    # Gyroscope-based restlessness score
    # ON — Verity has gyro, H10 didn't. This is a new capability.
    ENABLE_RESTLESSNESS_SCORE: bool = True

    # Hardmode sessions (Level 3+)
    # ON — triggers when RMSSD < hardmode threshold
    ENABLE_HARDMODE_SESSIONS: bool = True

    # AI coach (LLM-generated messages)
    # Can be set to False to fall back to rule-based template messages
    ENABLE_AI_COACH: bool = True

    # Conversational coach (voice/text feedback loop)
    # OFF until core coaching loop is validated
    ENABLE_CONVERSATION: bool = False

    # 30-day baseline re-run
    ENABLE_MONTHLY_REBASELINE: bool = True

    # Android Health Connect ingestion (sleep, steps, activity)
    ENABLE_HEALTH_CONNECT: bool = True

    # Stress fingerprint heat map
    # Requires 14+ days of data — auto-disables if insufficient history
    ENABLE_STRESS_FINGERPRINT: bool = True

    model_config = {"env_prefix": "ZENFLOW_FEATURE_", "extra": "ignore"}
