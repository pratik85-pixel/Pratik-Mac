"""sessions — session prescription, pacer config, and step-down gate logic."""

from sessions.practice_registry import (
    PracticeDescriptor,
    VALID_PRACTICE_TYPES,
    VALID_ATTENTION_ANCHORS,
    get_practice,
    is_available_at_stage,
    practices_for_stage,
)
from sessions.pacer_config import PacerConfig, build_pacer_config
from sessions.step_down_controller import (
    GateEvaluation,
    StepDownController,
)
from sessions.session_schema import PracticeSession
from sessions.session_prescriber import (
    PRF_UNKNOWN,
    PRF_FOUND,
    PRF_CONFIRMED,
    prescribe_session,
)

__all__ = [
    # Practice registry
    "PracticeDescriptor",
    "VALID_PRACTICE_TYPES",
    "VALID_ATTENTION_ANCHORS",
    "get_practice",
    "is_available_at_stage",
    "practices_for_stage",
    # Pacer
    "PacerConfig",
    "build_pacer_config",
    # Step-down controller
    "GateEvaluation",
    "StepDownController",
    # Session schema
    "PracticeSession",
    # Prescriber
    "PRF_UNKNOWN",
    "PRF_FOUND",
    "PRF_CONFIRMED",
    "prescribe_session",
]
