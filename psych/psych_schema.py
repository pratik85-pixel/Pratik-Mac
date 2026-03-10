"""
psych/psych_schema.py

Pure-Python dataclasses for the psychological profile layer.

All score-bearing fields use 0–100 scale (same as readiness/stress/recovery)
so the coach can reference them without units.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


# ── Trigger taxonomy ──────────────────────────────────────────────────────────

ANXIETY_TRIGGER_TYPES: tuple[str, ...] = (
    "deadline",
    "social_pressure",
    "financial",
    "health_worry",
    "performance",
    "confrontation",
    "crowds",
    "uncertainty",
    "work_overload",
    "relationship",
    "change",
    "unknown",
)

SEVERITY_WEIGHT: dict[str, float] = {
    "mild":     0.33,
    "moderate": 0.66,
    "severe":   1.0,
}


# ── Input records ─────────────────────────────────────────────────────────────

@dataclass
class SocialEvent:
    """One tagged social_time window with its physiological impact as scores."""
    recovery_score_before: float   # 0–100
    recovery_score_after:  float   # 0–100 (within 2h of event end)
    duration_minutes:      float
    event_id:              Optional[str]      = field(default=None)
    ts:                    Optional[datetime] = field(default=None)


@dataclass
class TaggedActivityRecord:
    """A tagged window (stress or recovery) with associated score change."""
    slug:                str
    category:            str       # from activity catalog
    stress_or_recovery:  str       # "stress" | "recovery"
    score_delta:         float     # recovery-score points change post-event
    duration_minutes:    float
    ts:                  Optional[datetime] = field(default=None)


@dataclass
class AnxietyEventRecord:
    """Raw anxiety event for profile aggregation."""
    trigger_type:          str
    severity:              str       # "mild"|"moderate"|"severe"
    stress_score_at_event: float     # 0–100
    event_id:              Optional[str]      = field(default=None)
    ts:                    Optional[datetime] = field(default=None)
    recovery_score_drop:   Optional[float]    = field(default=None)
    resolution_activity:   Optional[str]      = field(default=None)
    resolved:              bool               = False


@dataclass
class MoodRecord:
    """One MoodLog row in plain Python."""
    mood_score:    float           # 1–5 (float to support inferred scores)
    energy_score:  Optional[float]
    anxiety_score: Optional[float]
    social_desire: Optional[float]
    readiness_score_at_log:  Optional[float]    # 0–100
    stress_score_at_log:     Optional[float]    = field(default=None)  # 0–100
    recovery_score_at_log:   Optional[float]    = field(default=None)  # 0–100
    ts:                      Optional[datetime] = field(default=None)


@dataclass
class PlanAdherence:
    """Plan execution record for discipline index computation."""
    plan_date:  date    # date of the plan
    planned:    int     # items generated
    completed:  int     # items completed (planned - deviations)

    @property
    def date_str(self) -> str:
        return self.plan_date.isoformat()


# ── Output profile ────────────────────────────────────────────────────────────

@dataclass
class AnxiestTrigger:
    trigger_type: str
    count:        int
    avg_severity: float    # 0–1
    strength:     float    # 0–1 = (count × avg_severity) normalised


@dataclass
class ActivityImpact:
    slug:         str
    count:        int
    avg_score_delta: float   # recovery-score points (positive = lifts, negative = costs)


@dataclass
class PsychProfile:
    """
    Computed psychological/behavioural fingerprint.

    All numeric fields use interpretable 0–100 or labelled scales
    so the coach can reference them directly as scores.
    """

    # Social energy
    social_energy_type:   str     # "introvert"|"ambivert"|"extrovert"|"unknown"
    social_hrv_delta_avg: float   # mean recovery-score delta during social events
    social_event_count:   int

    # Anxiety
    anxiety_sensitivity:   float             # 0–1
    top_anxiety_triggers:  list[AnxiestTrigger]

    # Activity ↔ score map
    top_calming_activities: list[ActivityImpact]
    top_stress_activities:  list[ActivityImpact]

    # Recovery style
    primary_recovery_style: str   # "physical"|"social"|"solo_passive"|"nature"|"mindfulness"|"sleep"

    # Discipline
    discipline_index: float   # 0–100
    streak_current:   int
    streak_best:      int

    # Mood
    mood_baseline:  str           # "low"|"moderate"|"high"
    mood_score_avg: Optional[float]

    # Interoception alignment
    interoception_alignment: Optional[float]   # Pearson r

    # Metadata
    data_confidence:  float   # 0–1
    coach_insight:    Optional[str]   # pre-built 1-sentence insight for morning brief

    def to_dict(self) -> dict:
        """Serialise to a JSON-safe dict for DB storage."""
        return {
            "social_energy_type":      self.social_energy_type,
            "social_hrv_delta_avg":    self.social_hrv_delta_avg,
            "social_event_count":      self.social_event_count,
            "anxiety_sensitivity":     round(self.anxiety_sensitivity, 3),
            "top_anxiety_triggers":    [
                {
                    "type": t.trigger_type,
                    "count": t.count,
                    "avg_severity": round(t.avg_severity, 3),
                    "strength": round(t.strength, 3),
                }
                for t in self.top_anxiety_triggers
            ],
            "top_calming_activities":  [
                {"slug": a.slug, "count": a.count, "avg_score_delta": round(a.avg_score_delta, 1)}
                for a in self.top_calming_activities
            ],
            "top_stress_activities":   [
                {"slug": a.slug, "count": a.count, "avg_score_delta": round(a.avg_score_delta, 1)}
                for a in self.top_stress_activities
            ],
            "primary_recovery_style":  self.primary_recovery_style,
            "discipline_index":        round(self.discipline_index, 1),
            "streak_current":          self.streak_current,
            "streak_best":             self.streak_best,
            "mood_baseline":           self.mood_baseline,
            "mood_score_avg":          round(self.mood_score_avg, 2) if self.mood_score_avg else None,
            "interoception_alignment": round(self.interoception_alignment, 3) if self.interoception_alignment is not None else None,
            "data_confidence":         round(self.data_confidence, 3),
            "coach_insight":           self.coach_insight,
        }
