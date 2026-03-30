"""
Phase 3B — Plan prescriber readiness (explicit contract).

This is **not** the same as intraday ``net_balance`` / locked display metrics.
It is the coach.plan_replanner load_score mapped to 0–100 for DailyPlan.

Tracking summaries may expose ``net_balance`` / waking recovery etc. under
``METRICS_CONTRACT_ID``; plan rows expose ``readiness_formula_id`` below.
"""

from __future__ import annotations

from typing import Literal

from tracking.locked_metrics_contract import METRICS_CONTRACT_ID

# Bump only if the mapping from load_score → readiness or day_type thresholds change.
PLAN_READINESS_FORMULA_ID = "plan_load_inverse_v1"

PlanDayType = Literal["green", "yellow", "red"]


def plan_readiness_from_load_score(load_score: float) -> float:
    """Map plan_replanner load_score (0–1, higher = more pressured) to 0–100 readiness."""
    return round((1.0 - min(float(load_score), 1.0)) * 100, 1)


def plan_day_type_from_load_score(load_score: float) -> PlanDayType:
    ls = float(load_score)
    if ls < 0.35:
        return "green"
    if ls < 0.65:
        return "yellow"
    return "red"


def plan_api_contract_metadata() -> dict[str, str]:
    """Fields to merge into plan API payloads for client transparency."""
    return {
        "metrics_contract_id": METRICS_CONTRACT_ID,
        "readiness_formula_id": PLAN_READINESS_FORMULA_ID,
    }
