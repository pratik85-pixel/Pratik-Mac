"""
Phase 1 — Scientific scoring core (metrics locked).

Defines the public contract id for the four locked display metrics and derives
**non-scoring** confidence metadata from existing flags. This module MUST NOT
change stress, waking recovery, sleep recovery, or client-side readiness math.
"""

from __future__ import annotations

from typing import Literal

# Bump only when the API contract (field meanings or units) changes — not when
# internal refactors occur while preserving numeric outputs.
METRICS_CONTRACT_ID: str = "zenflow_locked_v1"

ScoreConfidence = Literal["high", "medium", "low"]
SummarySource = Literal["live_compute", "persisted_row"]


def classify_score_confidence(
    *,
    is_estimated: bool,
    is_partial_data: bool,
    calibration_days: int,
) -> tuple[ScoreConfidence, list[str]]:
    """
    Map existing pipeline flags to a coarse confidence level + machine-readable reasons.

    Does not modify or rescale any score values.
    """
    reasons: list[str] = []
    if is_partial_data:
        reasons.append("partial_day")
    if is_estimated:
        reasons.append("calibration_incomplete")
    if calibration_days <= 0:
        reasons.append("limited_baseline_history")

    if is_partial_data:
        return ("low", reasons)
    if is_estimated:
        return ("medium", reasons)
    return ("high", reasons)


def contract_metadata_for_row(
    *,
    is_estimated: bool,
    is_partial_data: bool,
    calibration_days: int,
    summary_source: SummarySource,
) -> dict:
    """Payload fields to merge into API responses (Pydantic models)."""
    conf, reasons = classify_score_confidence(
        is_estimated=is_estimated,
        is_partial_data=is_partial_data,
        calibration_days=calibration_days,
    )
    return {
        "metrics_contract_id": METRICS_CONTRACT_ID,
        "score_confidence": conf,
        "score_confidence_reasons": reasons,
        "summary_source": summary_source,
    }
