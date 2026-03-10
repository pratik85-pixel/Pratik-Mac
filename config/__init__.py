"""
config/__init__.py

Single import point for all ZenFlow configuration.

Usage in any module:
    from config import CONFIG

    window  = CONFIG.processing.RSA_WINDOW_SECONDS
    zone3   = CONFIG.scoring.ZONE_3_MIN
    enabled = CONFIG.features.ENABLE_PAV_BREATH

Golden rule: If a numeric constant appears anywhere outside config/, it is a bug.
"""

from config.processing import ProcessingConfig
from config.scoring import ScoringConfig
from config.model import ModelConfig
from config.coach import CoachConfig
from config.features import FeatureFlags
from config.tracking import TrackingConfig
from config.versions import CONFIG_VERSION


class ZenFlowConfig:
    """Top-level config object. Assembles all domain configs into one namespace."""

    def __init__(self) -> None:
        self.processing = ProcessingConfig()
        self.scoring = ScoringConfig()
        self.model = ModelConfig()
        self.coach = CoachConfig()
        self.features = FeatureFlags()
        self.tracking = TrackingConfig()
        self.version = CONFIG_VERSION

    def __repr__(self) -> str:
        return f"ZenFlowConfig(version={self.version})"


# The one config object the entire codebase imports
CONFIG = ZenFlowConfig()
