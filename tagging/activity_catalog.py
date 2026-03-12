"""
Activity Catalog
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

@dataclass
class ActivityDef:
    slug: str
    category: str
    stress_or_recovery: str
    display_name: str
    evidence_signals: List[str] = field(default_factory=list)
    coach_follow_up: bool = False
    prescribable: bool = True
    recoverable: bool = False
    requires_session: bool = False

_CATALOG: List[ActivityDef] = [
    ActivityDef("running", "movement", "stress", "Running", ["hr", "hrm"]),
    ActivityDef("weight_training", "movement", "stress", "Weight Training", ["hr"]),
    ActivityDef("cycling", "movement", "stress", "Cycling", ["hr"]),
    ActivityDef("swimming", "movement", "stress", "Swimming", ["hr"]),
    ActivityDef("walking", "movement", "stress", "Walking", ["hr"]),
    ActivityDef("hiking", "movement", "stress", "Hiking", ["hr"]),
    ActivityDef("sports", "movement", "stress", "Sports", ["hr"], prescribable=True),
    ActivityDef("coherence_breathing", "recovery_active", "recovery", "ZenFlow session", ["hrv", "breath"], requires_session=True),
    ActivityDef("meditation", "recovery_active", "recovery", "Meditation", ["hrv"]),
    ActivityDef("journaling", "recovery_active", "recovery", "Journaling", []),
    ActivityDef("book_reading", "recovery_passive", "recovery", "Book Reading", []),
    ActivityDef("music", "recovery_passive", "recovery", "Music", []),
    ActivityDef("social_time", "recovery_passive", "recovery", "Social Time", [], coach_follow_up=True),
    ActivityDef("entertainment", "recovery_passive", "recovery", "Entertainment", [], coach_follow_up=True),
    ActivityDef("yoga", "recovery_active", "recovery", "Yoga", ["hrv", "movement"]),
    ActivityDef("cold_shower", "recovery_active", "recovery", "Cold Shower", ["hr", "hrv"], coach_follow_up=True),
    ActivityDef("nature_time", "recovery_passive", "recovery", "Nature Time", [], recoverable=True),
    ActivityDef("nap", "recovery_passive", "recovery", "Nap", ["hrv"], prescribable=False),
    ActivityDef("sleep", "recovery_passive", "recovery", "Sleep", ["hrv", "sleep"], prescribable=False),
    ActivityDef("work_sprint", "work", "stress", "Work Sprint", []),
    ActivityDef("commute", "work", "stress", "Commute", []),
]

CATALOG: Dict[str, ActivityDef] = {a.slug: a for a in _CATALOG}

COACH_FOLLOW_UP_SLUGS: Set[str] = {a.slug for a in _CATALOG if a.coach_follow_up}
RECOVERY_SLUGS: Set[str] = {a.slug for a in _CATALOG if a.stress_or_recovery == "recovery"}
MOVEMENT_SLUGS: Set[str] = {a.slug for a in _CATALOG if a.category == "movement"}

def get_activity(slug: str) -> Optional[ActivityDef]:
    return CATALOG.get(slug)

def get_display(slug: str, fallback: Optional[str] = None) -> str:
    act = get_activity(slug)
    if act:
        return act.display_name
    return fallback if fallback is not None else slug

def is_valid_slug(slug: str) -> bool:
    return slug in CATALOG

def is_recovery_activity(slug: str) -> bool:
    return slug in RECOVERY_SLUGS

def is_movement_activity(slug: str) -> bool:
    return slug in MOVEMENT_SLUGS

def needs_coach_follow_up(slug: str) -> bool:
    return slug in COACH_FOLLOW_UP_SLUGS

def slugs_for_category(category: str) -> Set[str]:
    return {a.slug for a in _CATALOG if a.category == category}
