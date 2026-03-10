"""
archetypes/__init__.py

Public API for the ZenFlow Verity archetype layer.

Usage:
    from archetypes import compute_ns_health_profile, compute_narrative, NSHealthProfile, NSNarrative

    profile   = compute_ns_health_profile(fingerprint)
    narrative = compute_narrative(profile)
"""

from archetypes.scorer import (
    NSHealthProfile,
    compute_ns_health_profile,
    STAGE_THRESHOLDS,
    STAGE_TARGETS,
)
from archetypes.narrative import (
    NSNarrative,
    compute_narrative,
)

__all__ = [
    # Core compute functions
    "compute_ns_health_profile",
    "compute_narrative",
    # Output dataclasses
    "NSHealthProfile",
    "NSNarrative",
    # Constants
    "STAGE_THRESHOLDS",
    "STAGE_TARGETS",
]
