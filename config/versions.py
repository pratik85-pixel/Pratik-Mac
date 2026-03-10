"""
config/versions.py

Config version registry.

Rules:
  - Bump CONFIG_VERSION whenever any threshold in scoring.py changes.
  - Add a snapshot of the changed values to VERSION_HISTORY.
  - Every session and outcome record stores the config_version it was
    computed with — so recalculation on old data uses the correct thresholds.
  - Never delete history entries.
"""

# Current config version — bump when scoring thresholds change
CONFIG_VERSION: int = 1

# Snapshot of scoring values at each version
# Only record values that changed from the previous version
VERSION_HISTORY: dict[int, dict] = {
    1: {
        "description": "Initial version — Verity Sense project baseline",
        "date": "2026-03-07",
        "changed": {
            "ZONE_3_MIN": 0.60,
            "ZONE_4_MIN": 0.80,
            "LEVEL_1_COHERENCE_AVG_THRESHOLD": 0.60,
            "HARDMODE_RMSSD_THRESHOLD_PCT": 0.85,
            "RECOVERY_ARC_RETURN_THRESHOLD_PCT": 0.90,
        },
    },
    # Future example:
    # 2: {
    #     "description": "Raised Zone 3 after cohort data review",
    #     "date": "2026-04-01",
    #     "changed": {"ZONE_3_MIN": 0.62},
    # },
}
