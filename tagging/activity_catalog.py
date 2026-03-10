"""
tagging/activity_catalog.py

Canonical activity catalog.

Every slug used in StressWindow.tag / RecoveryWindow.tag must appear here.
The catalog drives:
  - Tag nudge display names (ActivityDefinition.display)
  - Auto-tagger evidence matching (ActivityDefinition.evidence_signals)
  - Prescriber item construction (ActivityDefinition.category, stress_or_recovery)
  - Coach context (ActivityDefinition.coach_follow_up → proactive question policy)
  - DailyPlan item pool (ActivityDefinition.prescribable)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ── ActivityDefinition ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ActivityDefinition:
    """
    Single entry in the activity catalog.

    Attributes
    ----------
    slug : str
        Unique internal key.  Use underscores, no spaces.
    display : str
        Human-facing name shown in the UI.
    category : str
        One of: movement | zenflow_session | mindfulness |
                habitual_relaxation | sleep | recovery_active
    stress_or_recovery : str
        "stress" | "recovery" | "mixed"
    recoverable : bool
        True when the activity typically produces a recovery window
        (i.e., RMSSD rises during/after it).
    evidence_signals : tuple[str, ...]
        Sensor signals that can passively identify this activity without a tag.
        Empty tuple = no passive detection; coach_follow_up should be True.
    metric_schema : tuple[str, ...]
        Optional user-reported metrics (for structured capture prompts).
    requires_session : bool
        True when a live ZenFlow session UUID must be linked.
    coach_follow_up : bool
        True when the coach should ask about this proactively because no sensor
        signal is available (e.g. "Did you go out last night?").
    prescribable : bool
        True when the prescriber may include this as a plan item.
    social_energy_effect : str
        How this activity affects social battery:
        "energising" = tends to lift social energy (e.g. social_time for extroverts),
        "draining"   = tends to cost social energy (e.g. crowds, commute),
        "neutral"    = no reliable social-energy signal.
        The psych_profile_builder overrides this default with the user's *actual*
        measured HRV/recovery response.
    notes : str
        Internal notes for developers / coach prompt authors.
    """
    slug:                 str
    display:              str
    category:             str
    stress_or_recovery:   str
    recoverable:          bool
    evidence_signals:     tuple[str, ...] = field(default_factory=tuple)
    metric_schema:        tuple[str, ...] = field(default_factory=tuple)
    requires_session:     bool  = False
    coach_follow_up:      bool  = False
    prescribable:         bool  = True
    social_energy_effect: str   = "neutral"
    notes:                str   = ""


# ── Seed catalog ──────────────────────────────────────────────────────────────

_CATALOG: list[ActivityDefinition] = [

    # ── Movement — physical stress ─────────────────────────────────────────
    ActivityDefinition(
        slug="running",
        display="Running",
        category="movement",
        stress_or_recovery="stress",
        recoverable=True,
        evidence_signals=("acc_high_motion", "hr_elevated", "stress_window_present"),
        metric_schema=("duration_min", "distance_km", "hr_zone"),
        social_energy_effect="neutral",
    ),
    ActivityDefinition(
        slug="weight_training",
        display="Weight training",
        category="movement",
        stress_or_recovery="stress",
        recoverable=True,
        evidence_signals=("acc_high_motion", "hr_elevated", "stress_window_present"),
        metric_schema=("duration_min", "hr_zone"),
        social_energy_effect="neutral",
    ),
    ActivityDefinition(
        slug="cycling",
        display="Cycling",
        category="movement",
        stress_or_recovery="stress",
        recoverable=False,
        evidence_signals=("acc_high_motion", "hr_elevated"),
        metric_schema=("duration_min", "distance_km", "hr_zone"),
        social_energy_effect="neutral",
    ),
    ActivityDefinition(
        slug="swimming",
        display="Swimming",
        category="movement",
        stress_or_recovery="stress",
        recoverable=False,
        evidence_signals=("hr_elevated", "stress_window_present"),
        metric_schema=("duration_min", "laps"),
        social_energy_effect="neutral",
        notes="ACC may not trigger due to in-water motion patterns.",
    ),
    ActivityDefinition(
        slug="walking",
        display="Walking",
        category="movement",
        stress_or_recovery="mixed",
        recoverable=True,
        evidence_signals=("acc_low_motion", "hr_slightly_elevated"),
        metric_schema=("duration_min", "distance_km"),
        social_energy_effect="neutral",
    ),
    ActivityDefinition(
        slug="hiking",
        display="Hiking",
        category="movement",
        stress_or_recovery="mixed",
        recoverable=False,
        evidence_signals=("acc_sustained_motion", "hr_slightly_elevated"),
        metric_schema=("duration_min", "distance_km"),
        social_energy_effect="neutral",
    ),
    ActivityDefinition(
        slug="sports",
        display="Sports / games",
        category="movement",
        stress_or_recovery="stress",
        recoverable=True,
        evidence_signals=("acc_high_motion", "hr_elevated", "stress_window_present"),
        metric_schema=("duration_min", "sport_name"),
        coach_follow_up=True,
        social_energy_effect="energising",
        notes=(
            "User-defined via onboarding movement_enjoyed "
            "(pickleball, tennis, basketball, etc.). "
            "If consistently produces high stress_contribution_pct + slow next-day "
            "recovery → enters CoachContext as known stressor."
        ),
    ),

    # ── ZenFlow session ────────────────────────────────────────────────────
    ActivityDefinition(
        slug="coherence_breathing",
        display="ZenFlow session",
        category="zenflow_session",
        stress_or_recovery="recovery",
        recoverable=True,
        evidence_signals=("linked_session_id",),
        metric_schema=("duration_min", "coherence_avg", "session_score"),
        requires_session=True,
        prescribable=True,
        social_energy_effect="neutral",
        notes="Always must_do in DailyPlan.",
    ),

    # ── Mindfulness ────────────────────────────────────────────────────────
    ActivityDefinition(
        slug="meditation",
        display="Meditation",
        category="mindfulness",
        stress_or_recovery="recovery",
        recoverable=True,
        evidence_signals=("low_motion", "recovery_window_present"),
        metric_schema=("duration_min",),
        social_energy_effect="neutral",
    ),
    ActivityDefinition(
        slug="journaling",
        display="Journaling",
        category="mindfulness",
        stress_or_recovery="recovery",
        recoverable=True,
        evidence_signals=("low_motion",),
        metric_schema=("duration_min",),
        social_energy_effect="neutral",
    ),

    # ── Habitual relaxation ────────────────────────────────────────────────
    ActivityDefinition(
        slug="book_reading",
        display="Reading",
        category="habitual_relaxation",
        stress_or_recovery="recovery",
        recoverable=True,
        evidence_signals=("low_motion", "recovery_window_present"),
        metric_schema=("duration_min",),
        social_energy_effect="neutral",
    ),
    ActivityDefinition(
        slug="music",
        display="Music / listening",
        category="habitual_relaxation",
        stress_or_recovery="recovery",
        recoverable=True,
        evidence_signals=("low_motion", "recovery_window_present"),
        metric_schema=("duration_min",),
        social_energy_effect="neutral",
    ),
    ActivityDefinition(
        slug="social_time",
        display="Social time",
        category="habitual_relaxation",
        stress_or_recovery="recovery",
        recoverable=False,
        evidence_signals=(),
        metric_schema=("duration_min",),
        coach_follow_up=True,
        social_energy_effect="energising",
        notes=(
            "No sensor signal — coach asks proactively to build context and "
            "relationship, not to tag. Default social_energy_effect=energising "
            "(oxytocin pathway); psych_profile_builder overrides per user data."
        ),
    ),
    ActivityDefinition(
        slug="entertainment",
        display="Movie / TV",
        category="habitual_relaxation",
        stress_or_recovery="recovery",
        recoverable=False,
        evidence_signals=(),
        metric_schema=("duration_min",),
        coach_follow_up=True,
        social_energy_effect="neutral",
        notes="No sensor signal. Prescribable as genuine rest on red/yellow days.",
    ),

    # ── Recovery active ────────────────────────────────────────────────────
    ActivityDefinition(
        slug="yoga",
        display="Yoga",
        category="recovery_active",
        stress_or_recovery="recovery",
        recoverable=True,
        evidence_signals=("low_motion", "recovery_window_present"),
        metric_schema=("duration_min",),
        social_energy_effect="neutral",
    ),
    ActivityDefinition(
        slug="cold_shower",
        display="Cold shower",
        category="recovery_active",
        stress_or_recovery="recovery",
        recoverable=True,
        evidence_signals=(),
        metric_schema=("duration_min",),
        coach_follow_up=True,
        social_energy_effect="neutral",
        notes=(
            "Produces strongest vagal rebound available outside a ZenFlow session. "
            "No reliable sensor signature — short duration and controlled environment."
        ),
    ),
    ActivityDefinition(
        slug="nature_time",
        display="Time in nature",
        category="recovery_active",
        stress_or_recovery="recovery",
        recoverable=True,
        evidence_signals=("acc_low_motion", "recovery_window_likely"),
        metric_schema=("duration_min",),
        social_energy_effect="neutral",
        notes="Low ACC movement + recovery window likely. Prescribable as genuine recovery.",
    ),

    # ── Sleep ──────────────────────────────────────────────────────────────
    ActivityDefinition(
        slug="nap",
        display="Nap",
        category="sleep",
        stress_or_recovery="recovery",
        recoverable=True,
        evidence_signals=("low_motion", "recovery_window_present", "sleep_context"),
        metric_schema=("duration_min",),
        social_energy_effect="neutral",
    ),
    ActivityDefinition(
        slug="sleep",
        display="Sleep",
        category="sleep",
        stress_or_recovery="recovery",
        recoverable=True,
        evidence_signals=("sleep_context", "overnight_recovery_window"),
        metric_schema=("duration_min",),
        prescribable=False,
        social_energy_effect="neutral",
        notes="Auto-tagged; never manually prescribed in DailyPlan.",
    ),

    # ── Habitual stress ────────────────────────────────────────────────────
    ActivityDefinition(
        slug="work_sprint",
        display="Work block",
        category="movement",
        stress_or_recovery="stress",
        recoverable=True,
        evidence_signals=("low_motion", "stress_window_present"),
        metric_schema=("duration_min",),
        prescribable=False,
        social_energy_effect="neutral",
        notes="Auto-detected from waking background windows.",
    ),
    ActivityDefinition(
        slug="commute",
        display="Commute",
        category="movement",
        stress_or_recovery="mixed",
        recoverable=True,
        evidence_signals=("acc_sustained_motion", "stress_window_maybe"),
        metric_schema=("duration_min",),
        prescribable=False,
        social_energy_effect="draining",
    ),
]

# ── Lookup structures (built once at import) ──────────────────────────────────

CATALOG: dict[str, ActivityDefinition] = {a.slug: a for a in _CATALOG}

# All slugs whose coach_follow_up=True (proactive conversation prompts)
COACH_FOLLOW_UP_SLUGS: frozenset[str] = frozenset(
    a.slug for a in _CATALOG if a.coach_follow_up
)

# All prescribable slugs grouped by category
PRESCRIBABLE_BY_CATEGORY: dict[str, list[str]] = {}
for _act in _CATALOG:
    if _act.prescribable:
        PRESCRIBABLE_BY_CATEGORY.setdefault(_act.category, []).append(_act.slug)

# Slugs that are recovery activities (for DailyPlan optional slot)
RECOVERY_SLUGS: frozenset[str] = frozenset(
    a.slug for a in _CATALOG
    if a.stress_or_recovery == "recovery" and a.prescribable
)

# Slugs for physical movement (for DailyPlan recommended slot on green days)
MOVEMENT_SLUGS: frozenset[str] = frozenset(
    a.slug for a in _CATALOG
    if a.category == "movement" and a.prescribable
)

# Slugs that are crowd/social-draining by default
SOCIAL_DRAINING_SLUGS: frozenset[str] = frozenset(
    a.slug for a in _CATALOG if a.social_energy_effect == "draining"
)

# Slugs that are social-energising by default
SOCIAL_ENERGISING_SLUGS: frozenset[str] = frozenset(
    a.slug for a in _CATALOG if a.social_energy_effect == "energising"
)


# ── Public helpers ────────────────────────────────────────────────────────────

def get_activity(slug: str) -> Optional[ActivityDefinition]:
    """Return the ActivityDefinition for a slug, or None if not found."""
    return CATALOG.get(slug)


def is_valid_slug(slug: str) -> bool:
    """Return True if the slug exists in the catalog."""
    return slug in CATALOG


def get_display(slug: str, fallback: str = "") -> str:
    """Return the human display name for a slug."""
    act = CATALOG.get(slug)
    return act.display if act else fallback


def slugs_for_category(category: str) -> list[str]:
    """Return all prescribable slugs in a given category."""
    return list(PRESCRIBABLE_BY_CATEGORY.get(category, []))


def is_recovery_activity(slug: str) -> bool:
    """Return True if this activity is a recovery prescription (not movement stress)."""
    return slug in RECOVERY_SLUGS


def is_movement_activity(slug: str) -> bool:
    """Return True if this activity is movement-category and prescribable."""
    return slug in MOVEMENT_SLUGS


def needs_coach_follow_up(slug: str) -> bool:
    """Return True if the coach should ask about this activity proactively."""
    return slug in COACH_FOLLOW_UP_SLUGS
