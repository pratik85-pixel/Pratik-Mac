"""
Phase 3B — Composite readiness + plan day typing (explicit contract).

Composite readiness is computed from yesterday's display metrics (waking recovery,
sleep recovery, stress load) and stored on ``DailyStressSummary.readiness_score``.

Plan prescriber and DailyPlan use this 0–100 score directly — not an internal
``load_score`` mapping.

Tracking summaries may expose ``net_balance`` / waking recovery etc. under
``METRICS_CONTRACT_ID``; plan rows expose ``readiness_formula_id`` below.
"""

from __future__ import annotations

from typing import Literal, Optional

from tracking.locked_metrics_contract import METRICS_CONTRACT_ID

# Bump when weights, thresholds, or composite formula change.
PLAN_READINESS_FORMULA_ID = "composite_readiness_v2"

PlanDayType = Literal["green", "yellow", "relaxed", "red"]


def compute_composite_readiness(
    waking_recovery: Optional[float],
    sleep_recovery: Optional[float],
    stress_load_0_10: Optional[float],
) -> Optional[float]:
    """
    Combine yesterday's three display scores into a 0–100 readiness for today.

    stress_load_0_10: stress on the same 0–10 scale shown in the app
    (DailyStressSummary.stress_load_score is stored 0–100 → divide by 10).

    v2 weights (sleep-first): 0.45×sleep + 0.30×waking + 0.25×(10−stress)×10.
    Natural range [0, 100] when inputs are in range; clamped defensively.
    """
    if waking_recovery is None or stress_load_0_10 is None:
        return None
    try:
        w = float(waking_recovery)
        s = float(sleep_recovery) if sleep_recovery is not None else 0.0
        stress = max(0.0, min(10.0, float(stress_load_0_10)))
        raw = 0.45 * s + 0.30 * w + 0.25 * (10.0 - stress) * 10.0
        return round(max(0.0, min(100.0, raw)), 1)
    except (TypeError, ValueError):
        return None


def day_type_from_readiness(readiness: float) -> PlanDayType:
    """Map composite readiness (0–100) to plan / coach day label (4 tiers)."""
    r = float(readiness)
    if r > 75:
        return "green"
    if r >= 50:
        return "yellow"
    if r >= 25:
        return "relaxed"
    return "red"


def plan_api_contract_metadata() -> dict[str, str]:
    """Fields to merge into plan API payloads for client transparency."""
    return {
        "metrics_contract_id": METRICS_CONTRACT_ID,
        "readiness_formula_id": PLAN_READINESS_FORMULA_ID,
    }
