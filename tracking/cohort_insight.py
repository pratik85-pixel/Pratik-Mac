"""
Approximate peer context for stress index (Phase 7, opt-in).

Not population-validated — wide variance between individuals. Copy must always
show disclaimer; legal/product sign-off required before marketing claims.
"""

from __future__ import annotations

from typing import Optional

# Placeholder prior: "typical" band around mid index (tunable)
_PRIOR_CENTER = 0.42
_PRIOR_HALF_WIDTH = 0.22

DISCLAIMER = (
    "Approximate peer context for your age group. Not medical advice; "
    "wide individual variation."
)


def build_cohort_insight(
    *,
    include_requested: bool,
    user_opt_in: bool,
    stress_index: Optional[float],
    age_years: Optional[int],
) -> tuple[bool, Optional[str], str]:
    """
    Returns (enabled, band, disclaimer).

    band: below_typical | typical | above_typical — crude vs prior center.
    """
    if not include_requested or not user_opt_in or stress_index is None:
        return False, None, DISCLAIMER

    # Age currently unused in heuristic — hook for future stratification
    _ = age_years

    lo = _PRIOR_CENTER - _PRIOR_HALF_WIDTH
    hi = _PRIOR_CENTER + _PRIOR_HALF_WIDTH
    if stress_index < lo:
        band = "below_typical"
    elif stress_index > hi:
        band = "above_typical"
    else:
        band = "typical"

    return True, band, DISCLAIMER
