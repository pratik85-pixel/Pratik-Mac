"""
profile/plan_guardrails.py

Layer 3 — Deterministic validation and correction of the LLM-generated plan.

Runs after nightly_analyst.run_layer2_plan() before the plan is committed
to daily_plans table.

Rules are explicit Python — no LLM, no probabilistic decisions.
Each rule either:
  REJECTS: removes an item and logs a guardrail_note
  CAPS: limits a parameter (duration, count) and logs a guardrail_note
  INJECTS: adds an item that must always appear regardless of LLM output
  APPROVES: no change

Design contract
---------------
- Input:  list[PlanItem] from Layer 2 + UnifiedProfile + today's scores
- Output: ValidatedPlan(items, guardrail_notes, was_modified)
- Plan is ALWAYS non-empty after guardrails (fallback breathing item injected if needed)
- All guardrail decisions are logged in plan_guardrail_notes for auditability
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from profile.profile_schema import AvoidItem, PlanItem, UnifiedProfile
from tagging.activity_catalog import CATALOG

log = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────────

MAX_MUST_DO_HIGH_DISCIPLINE = 2   # discipline_index >= 40
MAX_MUST_DO_LOW_DISCIPLINE  = 1   # discipline_index < 40
MAX_TOTAL_ITEMS = 6

# Duration bounds per slug (min, max in minutes)
# Slugs not listed get default (5, 120)
_DURATION_BOUNDS: dict[str, tuple[int, int]] = {
    "breathing":       (5,  30),
    "walking":         (10, 60),
    "stretching":      (5,  30),
    "nap":             (10, 30),
    "cold_shower":     (2,  10),
    "book_reading":    (10, 60),
    "music":           (5,  60),
    "social_time":     (15, 120),
    "nature_time":     (15, 90),
    "work_sprint":     (25, 90),
    "sports":          (20, 120),
    "meditation":      (5,  45),
    "entertainment":   (15, 120),
    "commute":         (15, 90),
    "sleep_prep":      (10, 30),
}
_DEFAULT_DURATION_BOUNDS = (5, 120)

# Valid slugs (loaded from catalog)
_VALID_SLUGS: set[str] = set(CATALOG.keys())

# Emergency fallback item when plan would otherwise be empty
_FALLBACK_ITEM = PlanItem(
    slug="breathing",
    priority="must_do",
    duration_min=10,
    reason="Guardrail default — breathing session always available.",
)


# ── Output dataclass ──────────────────────────────────────────────────────────

@dataclass
class ValidatedPlan:
    items:           list[PlanItem]  = field(default_factory=list)
    avoid_items:     list[AvoidItem] = field(default_factory=list)
    guardrail_notes: list[str]       = field(default_factory=list)
    was_modified:    bool            = False


# ── Public API ────────────────────────────────────────────────────────────────

def validate_plan(
    items: list[PlanItem],
    profile: UnifiedProfile,
    *,
    avoid_items: Optional[list[AvoidItem]] = None,
    net_balance: Optional[float] = None,
    stress_score: Optional[int] = None,
    recovery_score: Optional[int] = None,
) -> ValidatedPlan:
    """
    Apply all guardrail rules in order.

    Rules are applied sequentially — each rule sees the output of the prior one.
    The plan after all rules is guaranteed non-empty.
    """
    # Cap avoid_items at 3 (LLM is instructed to send ≤3 but enforce here too)
    capped_avoid = (avoid_items or [])[:3]
    result   = ValidatedPlan(items=list(items), avoid_items=capped_avoid)
    nb       = net_balance if net_balance is not None else 0.0
    ss       = stress_score    if stress_score    is not None else 50
    disc     = profile.psych.discipline_index
    social   = profile.psych.social_energy_type
    tier     = profile.engagement.engagement_tier or "medium"

    # ── R1: Remove items with invalid slugs ───────────────────────────────────
    before = len(result.items)
    result.items = [i for i in result.items if i.slug in _VALID_SLUGS]
    removed = before - len(result.items)
    if removed:
        result.guardrail_notes.append(f"R1_invalid_slugs: removed {removed} items with unknown slugs")
        result.was_modified = True

    # ── R2: Clamp durations to allowed bounds per slug ────────────────────────
    for item in result.items:
        lo, hi = _DURATION_BOUNDS.get(item.slug, _DEFAULT_DURATION_BOUNDS)
        if item.duration_min < lo:
            result.guardrail_notes.append(
                f"R2_duration_floor: {item.slug} duration {item.duration_min}→{lo}min"
            )
            item.duration_min = lo
            result.was_modified = True
        elif item.duration_min > hi:
            result.guardrail_notes.append(
                f"R2_duration_ceiling: {item.slug} duration {item.duration_min}→{hi}min"
            )
            item.duration_min = hi
            result.was_modified = True

    # ── R3: Cap must_do count based on discipline_index ───────────────────────
    max_must_do = (
        MAX_MUST_DO_LOW_DISCIPLINE
        if (disc is not None and disc < 40)
        else MAX_MUST_DO_HIGH_DISCIPLINE
    )
    must_dos = [i for i in result.items if i.priority == "must_do"]
    if len(must_dos) > max_must_do:
        # Demote excess must_dos to recommended
        for item in must_dos[max_must_do:]:
            item.priority = "recommended"
            result.guardrail_notes.append(
                f"R3_must_do_cap: {item.slug} demoted must_do→recommended "
                f"(discipline={disc:.0f})" if disc is not None else "R3_must_do_cap"
            )
            result.was_modified = True

    # ── R4: Red balance — restorative items only ───────────────────────────────────────
    if nb < -20.0:
        performance_slugs = {"work_sprint", "sports", "cold_shower"}
        before = len(result.items)
        result.items = [i for i in result.items if i.slug not in performance_slugs]
        removed = before - len(result.items)
        if removed:
            result.guardrail_notes.append(
                f"R4_red_balance: removed {removed} performance items (net_balance={nb:.1f})"
            )
            result.was_modified = True

    # ── R5: Introvert + high stress → remove social_time ─────────────────────
    if social == "introvert" and ss > 70:
        before = len(result.items)
        result.items = [i for i in result.items if i.slug != "social_time"]
        if len(result.items) < before:
            result.guardrail_notes.append(
                f"R5_introvert_stress: removed social_time (introvert, stress={ss})"
            )
            result.was_modified = True

    # ── R6: Total items cap ───────────────────────────────────────────────────
    if len(result.items) > MAX_TOTAL_ITEMS:
        # Keep must_dos first, then recommended, then optional up to cap
        ordered = (
            [i for i in result.items if i.priority == "must_do"] +
            [i for i in result.items if i.priority == "recommended"] +
            [i for i in result.items if i.priority == "optional"]
        )
        result.items = ordered[:MAX_TOTAL_ITEMS]
        result.guardrail_notes.append(f"R6_total_cap: truncated to {MAX_TOTAL_ITEMS} items")
        result.was_modified = True

    # ── R7: At-risk / churned — ensure at least one frictionless item ─────────
    if tier in ("at_risk", "churned"):
        frictionless = {"breathing", "book_reading", "music", "stretching"}
        has_easy = any(i.slug in frictionless for i in result.items)
        if not has_easy:
            result.items.insert(0, PlanItem(
                slug="breathing",
                priority="recommended",
                duration_min=5,
                reason="Re-engagement item — 5-minute breathing to rebuild the daily habit.",
            ))
            result.guardrail_notes.append(
                f"R7_engagement: injected breathing for {tier} user"
            )
            result.was_modified = True

    # ── R8: Guarantee non-empty plan ─────────────────────────────────────────
    if not result.items:
        result.items = [_FALLBACK_ITEM]
        result.guardrail_notes.append("R8_empty_plan: injected fallback breathing item")
        result.was_modified = True

    log.debug(
        "guardrails: %d items, %d notes, modified=%s",
        len(result.items), len(result.guardrail_notes), result.was_modified,
    )
    return result
