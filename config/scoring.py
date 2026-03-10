"""
config/scoring.py

All threshold and scoring parameters.

These directly control user-visible outcomes (zone labels, level advancement,
resilience scores). Any change here MUST be paired with a CONFIG_VERSION bump
in versions.py, and all affected sessions/outcomes must be flagged for review.
"""

from pydantic_settings import BaseSettings


class ScoringConfig(BaseSettings):

    # ── Coherence / Sync Zones ────────────────────────────────────────────────
    # downstream: coherence_scorer, outcomes/session_outcomes,
    #             archetypes/classifier, ui ZoneIndicator colours
    #
    # UI labels:  Zone 1 = Settling | Zone 2 = Finding It
    #             Zone 3 = In Sync  | Zone 4 = Flow
    ZONE_1_MIN: float = 0.00   # Settling   — baseline, always present
    ZONE_2_MIN: float = 0.40   # Finding It
    ZONE_3_MIN: float = 0.60   # In Sync    — the primary training target
    ZONE_4_MIN: float = 0.80   # Flow       — peak state

    # downstream: outcomes/session_outcomes (session score calculation)
    # Session score = time-weighted avg of (coherence × zone_weight)
    ZONE_1_WEIGHT: float = 0.10
    ZONE_2_WEIGHT: float = 0.30
    ZONE_3_WEIGHT: float = 0.65
    ZONE_4_WEIGHT: float = 1.00

    # ── Session Scoring ───────────────────────────────────────────────────────

    # downstream: outcomes/session_outcomes, outcomes/level_gate
    # Minimum session duration (seconds) to be counted as valid
    SESSION_MIN_VALID_SECONDS: int = 120

    # ── Level Gates ───────────────────────────────────────────────────────────
    # downstream: outcomes/level_gate, archetypes/plan_prescriber
    # Physics-gated — time-blind. Could take 1 week or 4.

    # Level 1 → 2: coherence avg ≥ threshold across last N sessions
    LEVEL_1_COHERENCE_AVG_THRESHOLD: float = 0.60
    LEVEL_1_MIN_SESSIONS: int = 6

    # Level 2 → 3: hold Zone 3+ for N continuous minutes in M sessions
    LEVEL_2_ZONE3_CONTINUOUS_MINUTES: float = 4.0
    LEVEL_2_QUALIFYING_SESSIONS: int = 3

    # Level 3 → 4: complete N hardmode sessions with positive resilience delta
    LEVEL_3_HARDMODE_MIN_SESSIONS: int = 5

    # ── Resilience Score ──────────────────────────────────────────────────────
    # downstream: outcomes/weekly_outcomes, model/personal_distributions
    # Resilience = (today_rmssd / personal_ceiling) × 100, clipped 0–100
    RESILIENCE_PERSONAL_WINDOW_DAYS: int = 30

    # ── Recovery Arc ──────────────────────────────────────────────────────────
    # downstream: processing/recovery_arc, model/recovery_profiler
    # Arc ends when RMSSD returns to this fraction of the pre-stress baseline
    RECOVERY_ARC_RETURN_THRESHOLD_PCT: float = 0.90

    # Minimum stress-drop (ms) to register as a stress event worth tracking
    RECOVERY_ARC_MIN_RMSSD_DROP_MS: float = 5.0

    # ── Hardmode Trigger ──────────────────────────────────────────────────────
    # downstream: outcomes/hardmode_tracker, api/services/session_service
    # Hardmode triggered when morning RMSSD < (personal_floor × threshold)
    HARDMODE_RMSSD_THRESHOLD_PCT: float = 0.85

    model_config = {"env_prefix": "ZENFLOW_SCORING_", "extra": "ignore"}
