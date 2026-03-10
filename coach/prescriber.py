"""
coach/prescriber.py

Personalized DailyPlan generator.

This module generates the DailyPlan — the structured list of must_do,
recommended, and optional items for a user's day.  The LLM does NOT make
prescription decisions; it only translates the reason_code into language.

All prescription logic is deterministic Python.  The prescriber fires every
morning when a morning read arrives (or on demand via /plan/today).

Design inputs (25 total — DESIGN_V2 Section 11)
-----------------------------------------------
Fixed profile (rarely changes)
  1.  stage              — gates practice tier
  2.  archetype_primary  — pattern behaviour
  3.  flexibility        — high / medium / low (history window)
  4.  movement_enjoyed   — user onboarding preferences
  5.  decompress_via     — user decompression preferences
  6.  compliance_window  — best time-of-day to schedule
  7.  interoception_gap  — high gap → more explicit feedback in plan reasons
  8.  prf_status         — current practice unlock state
  9.  stage_focus        — from NSHealthProfile

Today's physiological state
  10. readiness_score
  11. day_type            — green / yellow / red
  12. morning_rmssd_quality
  13. morning_rmssd_vs_avg_pct

Rolling history
  14. rolling_readiness_14d   — list[float], recent first
  15. consecutive_net_negative_days
  16. yesterday_top_stressor
  17. yesterday_top_recovery

Behavioral signals
  18. confirmed_tags_7d       — list[str] activity slugs
  19. adherence_by_category   — dict[category, float]
  20. deviation_reason_history — list[str]
  21. day_of_week             — 0=Mon … 6=Sun
  22. available_windows       — list[str] e.g. ["07:00", "19:00"]

Recent context
  23. habit_events_72h        — list[HabitSignalSummary]
  24. conversation_signals    — list[str]
  25. plan_delta_net          — int (net plan changes from conversations)

Sport stressor override
  sport_overload_slugs       — list[str] from UserTagPatternModel
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional
from pydantic import BaseModel

from tagging.activity_catalog import (
    CATALOG,
    get_activity,
    get_display,
    slugs_for_category,
)

log = logging.getLogger(__name__)


# ── Constants ─────────────────────────────────────────────────────────────────

# Readiness score thresholds
GREEN_THRESHOLD:  float = 70.0
YELLOW_THRESHOLD: float = 45.0

# Flexibility → history window (days)
FLEXIBILITY_WINDOW: dict[str, int] = {
    "high":   3,
    "medium": 7,
    "low":    14,
}

# ZenFlow session durations per day type (minutes)
SESSION_DURATION: dict[str, int] = {
    "green":  20,
    "yellow": 10,
    "red":    5,
}

# Adherence floor — deprioritise category below this over 7 days
ADHERENCE_FLOOR: float = 0.50


# ── PlanItem (Pydantic for JSON / API serialisation) ─────────────────────────

class PlanItem(BaseModel):
    """A single item in a DailyPlan."""
    activity_slug:  str
    display:        str
    category:       str
    priority:       str          # "must_do" | "recommended" | "optional"
    duration_min:   Optional[int]
    reason_code:    str          # drives LLM language — plain machine token
    reason_note:    str          # human-readable rule note (not shown to user)


class DailyPlan(BaseModel):
    """
    The complete daily plan for a user.

    Items are organised into three priority buckets.
    The LLM receives this as context and translates reason_code + user profile
    into natural language coaching messages.
    """
    plan_date:     str           # ISO date string "YYYY-MM-DD"
    day_type:      str           # "green" | "yellow" | "red"
    readiness:     float
    stage:         int
    must_do:       list[PlanItem]
    recommended:   list[PlanItem]
    optional:      list[PlanItem]
    prescriber_notes: list[str]  # rules that fired — for coach context transparency


# ── Input type ────────────────────────────────────────────────────────────────

@dataclass
class PrescriberInputs:
    """
    All 25 inputs to the prescriber, plus sport stressor override.

    See module docstring for field descriptions.
    """
    # Fixed profile
    stage:              int
    archetype_primary:  str
    flexibility:        str             = "medium"
    movement_enjoyed:   list[str]       = field(default_factory=list)
    decompress_via:     list[str]       = field(default_factory=list)
    compliance_window:  Optional[str]   = None     # "HH:MM"
    interoception_gap:  Optional[float] = None
    prf_status:         Optional[str]   = None
    stage_focus:        Optional[str]   = None

    # Today's physio
    readiness_score:            float          = 50.0
    day_type:                   str            = "yellow"
    morning_rmssd_quality:      str            = "borderline"
    morning_rmssd_vs_avg_pct:   Optional[float] = None

    # Rolling history
    rolling_readiness_14d:          list[float]     = field(default_factory=list)
    consecutive_net_negative_days:  int             = 0
    yesterday_top_stressor:         Optional[str]   = None
    yesterday_top_recovery:         Optional[str]   = None

    # Behavioral
    confirmed_tags_7d:       list[str]          = field(default_factory=list)
    adherence_by_category:   dict[str, float]   = field(default_factory=dict)
    deviation_reason_history: list[str]         = field(default_factory=list)
    day_of_week:             int                = 0    # 0=Mon
    available_windows:       list[str]          = field(default_factory=list)

    # Recent context
    habit_events_72h:       list[str]   = field(default_factory=list)  # plain labels
    conversation_signals:   list[str]   = field(default_factory=list)
    plan_delta_net:         int         = 0

    # Sport stressor override
    sport_overload_slugs:   list[str]   = field(default_factory=list)

    # Plan date (ISO string)
    plan_date:              str         = "2026-03-10"


# ── Public API ────────────────────────────────────────────────────────────────

def build_daily_plan(inputs: PrescriberInputs) -> DailyPlan:
    """
    Build a DailyPlan from a fully populated PrescriberInputs.

    Deterministic — no randomness or LLM calls.  Same inputs always produce
    the same plan.

    Returns
    -------
    DailyPlan
        Pydantic model ready for DB storage and LLM context injection.
    """
    notes: list[str] = []
    must_do:      list[PlanItem] = []
    recommended:  list[PlanItem] = []
    optional_:    list[PlanItem] = []

    # ── Day type from readiness ───────────────────────────────────────────────
    day_type = _resolve_day_type(inputs.readiness_score, inputs.day_type)

    # ── Rule: always ZenFlow session as must_do ───────────────────────────────
    session_duration = SESSION_DURATION[day_type]
    must_do.append(PlanItem(
        activity_slug="coherence_breathing",
        display="ZenFlow session",
        category="zenflow_session",
        priority="must_do",
        duration_min=session_duration,
        reason_code="daily_session",
        reason_note=f"{day_type.capitalize()} day — {session_duration}min session.",
    ))

    # ── Rule: no intensity increase if consecutive negative ───────────────────
    allow_intensity = inputs.consecutive_net_negative_days < 3
    if not allow_intensity:
        notes.append(
            f"consecutive_net_negative_days={inputs.consecutive_net_negative_days} "
            f"— no intensity increase today."
        )

    # ── Rule: time_constraint deviation recurs → shorten targets ─────────────
    time_constrained = inputs.deviation_reason_history.count("time_constraint") >= 3
    if time_constrained:
        notes.append(
            "time_constraint recurred ≥3 times — duration targets reduced."
        )

    # ── Rule: deprioritise categories with <50% adherence last 7d ─────────────
    low_adherence_categories = {
        cat for cat, pct in inputs.adherence_by_category.items()
        if pct < ADHERENCE_FLOOR
    }
    if low_adherence_categories:
        notes.append(
            f"Deprioritised (low adherence): {', '.join(sorted(low_adherence_categories))}."
        )

    # ── Build recommended slot ────────────────────────────────────────────────
    if day_type == "green" and allow_intensity:
        rec = _select_movement(inputs, low_adherence_categories, notes)
        if rec:
            recommended.append(rec)
    elif day_type in ("yellow", "red"):
        # Light movement or social/passive recovery
        rec = _select_light_recovery(inputs, day_type, low_adherence_categories, notes)
        if rec:
            recommended.append(rec)

    # ── Build optional slot ───────────────────────────────────────────────────
    opt = _select_enjoyable_recovery(inputs, day_type, notes)
    if opt:
        optional_.append(opt)

    # ── Red day override: recommended = genuine rest ──────────────────────────
    if day_type == "red":
        recommended = [_rest_item(inputs, notes)]
        optional_ = []  # no optional on red — keep plan minimal

    # ── Sport stressor rule ───────────────────────────────────────────────────
    for item in recommended + optional_:
        if item.activity_slug == "sports" and item.activity_slug in inputs.sport_overload_slugs:
            # Remove sport if it's a known overload stressor
            to_remove = item
            if to_remove in recommended:
                recommended.remove(to_remove)
                notes.append(
                    "Sport omitted today — known overload stressor from tracking history."
                )

    return DailyPlan(
        plan_date=inputs.plan_date,
        day_type=day_type,
        readiness=inputs.readiness_score,
        stage=inputs.stage,
        must_do=must_do,
        recommended=recommended,
        optional=optional_,
        prescriber_notes=notes,
    )


# ── Selection helpers ─────────────────────────────────────────────────────────

def _resolve_day_type(readiness: float, declared_day_type: str) -> str:
    """Resolve day_type from readiness score, defaulting to declared type."""
    if readiness >= GREEN_THRESHOLD:
        return "green"
    if readiness >= YELLOW_THRESHOLD:
        return "yellow"
    return "red"


def _select_movement(
    inputs: PrescriberInputs,
    low_adherence_categories: set[str],
    notes: list[str],
) -> Optional[PlanItem]:
    """
    Select a movement item for green days.

    Preference order:
      1. From movement_enjoyed (onboarding preferences)
      2. Exclude sport_overload_slugs
      3. Fall back to walking if no preferences match
    """
    # Filter out deprioritised categories
    if "movement" in low_adherence_categories:
        notes.append("Movement category skipped — low adherence last 7 days.")
        return None

    # Try preferred movement slugs from onboarding
    preferred = [s for s in inputs.movement_enjoyed if s in CATALOG]
    # Remove sport stressors
    preferred = [s for s in preferred if s not in inputs.sport_overload_slugs]

    slug = preferred[0] if preferred else "walking"
    act = get_activity(slug)
    if act is None:
        slug = "walking"
        act = get_activity(slug)

    # Shorten duration if time-constrained
    duration = 30
    if inputs.deviation_reason_history.count("time_constraint") >= 3:
        duration = 20

    # Check sports: flag if it's a potential stressor
    reason_code = "preferred_movement"
    if slug == "sports":
        reason_code = "preferred_sport"

    return PlanItem(
        activity_slug=slug,
        display=get_display(slug, slug.replace("_", " ").title()),
        category="movement",
        priority="recommended",
        duration_min=duration,
        reason_code=reason_code,
        reason_note=f"From onboarding movement_enjoyed preference.",
    )


def _select_light_recovery(
    inputs: PrescriberInputs,
    day_type: str,
    low_adherence_categories: set[str],
    notes: list[str],
) -> Optional[PlanItem]:
    """
    Select a light recovery item for yellow days.

    Preference order:
      1. Light movement (walking, yoga) from movement_enjoyed if any
      2. Social recovery from decompress_via if present
      3. Fall back to walking
    """
    _LIGHT_MOVEMENT = {"walking", "yoga", "nature_time"}

    # Try light movement from preferences
    preferred_light = [
        s for s in inputs.movement_enjoyed
        if s in _LIGHT_MOVEMENT and s in CATALOG
    ]
    if preferred_light:
        slug = preferred_light[0]
        duration = 20 if inputs.deviation_reason_history.count("time_constraint") >= 3 else 30
        return PlanItem(
            activity_slug=slug,
            display=get_display(slug, slug.replace("_", " ").title()),
            category="recovery_active",
            priority="recommended",
            duration_min=duration,
            reason_code="light_movement_yellow",
            reason_note="Light movement on yellow day from preferences.",
        )

    # Try decompression preferences (social, entertainment, nature)
    _DECOMPRESS_SLUGS = {"social_time", "music", "book_reading", "nature_time"}
    preferred_decompress = [
        s for s in inputs.decompress_via
        if s in _DECOMPRESS_SLUGS and s in CATALOG
    ]
    if preferred_decompress:
        slug = preferred_decompress[0]
        act = get_activity(slug)
        return PlanItem(
            activity_slug=slug,
            display=get_display(slug, slug.replace("_", " ").title()),
            category=act.category if act else "habitual_relaxation",
            priority="recommended",
            duration_min=None,
            reason_code="decompress_yellow",
            reason_note="Decompression activity from preferences on yellow day.",
        )

    # Fallback to walking
    return PlanItem(
        activity_slug="walking",
        display="Walking",
        category="movement",
        priority="recommended",
        duration_min=20,
        reason_code="walk_fallback",
        reason_note="Default light movement on yellow day.",
    )


def _select_enjoyable_recovery(
    inputs: PrescriberInputs,
    day_type: str,
    notes: list[str],
) -> Optional[PlanItem]:
    """
    Select an optional enjoyable recovery item.

    Priority:
      1. cold_shower (if decompress_via or general wellness)
      2. social_time (if in decompress_via)
      3. entertainment (movie/TV — good rest signal)
      4. nature_time (if in decompress_via)
    """
    # Build priority list from decompress_via preferences
    _OPTIONAL_POOL = ["cold_shower", "social_time", "entertainment", "nature_time", "music", "book_reading"]

    # Prefer items that match decompress_via
    matched = [s for s in inputs.decompress_via if s in _OPTIONAL_POOL and s in CATALOG]
    # Add remaining from pool not already covered
    pool = matched + [s for s in _OPTIONAL_POOL if s not in matched and s in CATALOG]

    if not pool:
        return None

    slug = pool[0]
    act = get_activity(slug)
    return PlanItem(
        activity_slug=slug,
        display=get_display(slug, slug.replace("_", " ").title()),
        category=act.category if act else "habitual_relaxation",
        priority="optional",
        duration_min=None,
        reason_code=f"enjoyable_recovery_{day_type}",
        reason_note=f"Optional enjoyable recovery for {day_type} day.",
    )


def _rest_item(inputs: PrescriberInputs, notes: list[str]) -> PlanItem:
    """
    Build a genuine rest recommendation for red days.

    Picks the most personally relevant rest activity from decompress_via,
    with a note that this is genuine rest, not medical advice.
    """
    _REST_POOL = ["cold_shower", "entertainment", "social_time", "music", "book_reading"]

    matched = [s for s in inputs.decompress_via if s in _REST_POOL and s in CATALOG]
    slug = matched[0] if matched else "entertainment"
    act = get_activity(slug)

    notes.append("Red day: recommended is genuine rest — personal and enjoyable.")

    return PlanItem(
        activity_slug=slug,
        display=get_display(slug, slug.replace("_", " ").title()),
        category=act.category if act else "habitual_relaxation",
        priority="recommended",
        duration_min=None,
        reason_code="genuine_rest_red",
        reason_note="Genuine rest on red day — something enjoyable, not effortful.",
    )


# ── Serialisation helper ──────────────────────────────────────────────────────

def plan_to_items_json(plan: DailyPlan) -> list[dict]:
    """
    Flatten a DailyPlan into a list of item dicts for DB storage (DailyPlan.items_json).
    """
    items: list[dict] = []
    for item in plan.must_do + plan.recommended + plan.optional:
        items.append({
            "activity_slug": item.activity_slug,
            "display":       item.display,
            "category":      item.category,
            "priority":      item.priority,
            "duration_min":  item.duration_min,
            "reason_code":   item.reason_code,
        })
    return items


def build_daily_plan_from_uup(
    unified_profile: "Any",
    *,
    today: Optional[str] = None,
    readiness_score: float = 50.0,
    stage: int = 1,
) -> Optional[DailyPlan]:
    """
    Convert a persisted UnifiedProfile.suggested_plan into a DailyPlan.

    Returns None if the profile has no plan for today so the caller can fall
    back to the deterministic prescriber.

    Parameters
    ----------
    unified_profile
        A `profile.profile_schema.UnifiedProfile` instance.
    today
        ISO date string "YYYY-MM-DD". Defaults to today's UTC date.
    readiness_score
        Used to determine the day_type label on the output DailyPlan.
    stage
        User's HRV training stage.
    """
    from datetime import date as _date
    _today = today or str(_date.today())

    plan_items = getattr(unified_profile, "suggested_plan", None)
    plan_for_date = getattr(unified_profile, "plan_for_date", None)

    # Only use the UUP plan if it was built for today
    if not plan_items or str(plan_for_date) != _today:
        return None

    must_do:     list[PlanItem] = []
    recommended: list[PlanItem] = []
    optional_:   list[PlanItem] = []

    for uup_item in plan_items:
        slug = uup_item.slug
        act  = get_activity(slug)
        display  = get_display(slug, slug.replace("_", " ").title())
        category = act.category if act else "habitual_relaxation"

        item = PlanItem(
            activity_slug=slug,
            display=display,
            category=category,
            priority=uup_item.priority,
            duration_min=uup_item.duration_min,
            reason_code="uup_plan",
            reason_note=uup_item.reason or "From nightly Unified Profile plan.",
        )
        if uup_item.priority == "must_do":
            must_do.append(item)
        elif uup_item.priority == "recommended":
            recommended.append(item)
        else:
            optional_.append(item)

    if not must_do and not recommended and not optional_:
        return None

    day_type = _resolve_day_type(readiness_score, "green")

    return DailyPlan(
        plan_date=_today,
        day_type=day_type,
        readiness=readiness_score,
        stage=stage,
        must_do=must_do,
        recommended=recommended,
        optional=optional_,
        prescriber_notes=["plan_source: unified_profile_layer2"],
    )
