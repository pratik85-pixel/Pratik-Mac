"""
profile/profile_schema.py

Pure-Python dataclasses for the Unified User Profile layer.
No DB handles — these are the in-memory representation.

The top-level dataclass is UnifiedProfile.  It is:
  - built by unified_profile_builder.py from domain tables
  - enriched with narrative + plan by nightly_analyst.py
  - persisted by profile_service.py into user_unified_profiles
  - read by context_builder.py as the primary coach context lens
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


# ── Sub-dataclasses ───────────────────────────────────────────────────────────

@dataclass
class PhysiologicalTraits:
    prf_bpm:                    Optional[float] = None
    prf_status:                 Optional[str]   = None   # "PRF_UNKNOWN"|"PRF_FOUND"|"PRF_CONFIRMED"
    coherence_trainability:     Optional[str]   = None   # "low"|"moderate"|"high"
    recovery_arc_speed:         Optional[str]   = None   # "fast"|"normal"|"slow"
    stress_peak_pattern:        Optional[str]   = None   # "weekday 09:00–11:00"
    sleep_recovery_efficiency:  Optional[float] = None   # 0–1


@dataclass
class PsychologicalTraits:
    social_energy_type:      Optional[str]   = None   # "introvert"|"ambivert"|"extrovert"|"unknown"
    anxiety_sensitivity:     Optional[float] = None   # 0–1
    top_anxiety_triggers:    list[dict]      = field(default_factory=list)
    primary_recovery_style:  Optional[str]   = None
    discipline_index:        Optional[float] = None   # 0–100
    streak_current:          int             = 0
    mood_baseline:           Optional[str]   = None   # "low"|"moderate"|"high"
    interoception_alignment: Optional[float] = None   # Pearson r, -1 to 1


@dataclass
class BehaviouralPreferences:
    top_calming_activities: list[dict] = field(default_factory=list)
    top_stress_activities:  list[dict] = field(default_factory=list)
    # From UserHabits onboarding
    movement_enjoyed:  list[str] = field(default_factory=list)
    decompress_via:    list[str] = field(default_factory=list)
    stress_drivers:    list[str] = field(default_factory=list)
    alcohol:           Optional[str] = None
    caffeine:          Optional[str] = None
    sleep_schedule:    Optional[str] = None


@dataclass
class EngagementProfile:
    """
    How engaged the user is with the product — band + app combined.

    Used in the narrative and fed back into Layer 2 plan generation to
    adjust plan complexity and nudge intensity based on engagement level.
    """
    # Band engagement
    band_days_worn_last7:    Optional[int]   = None   # 0–7
    band_days_worn_last30:   Optional[int]   = None   # 0–30
    morning_read_streak:     int             = 0      # consecutive morning reads
    morning_read_rate_30d:   Optional[float] = None   # 0–1

    # App engagement
    sessions_last7:          int             = 0
    sessions_last30:         int             = 0
    conversations_last7:     int             = 0
    nudge_response_rate_30d: Optional[float] = None   # 0–1
    last_app_interaction_days: Optional[int] = None   # days since any interaction

    # Computed tier
    engagement_tier:  Optional[str] = None   # "high"|"medium"|"low"|"at_risk"|"churned"
    engagement_trend: Optional[str] = None   # "improving"|"stable"|"declining"

    def compute_tier(self) -> str:
        """
        Determine engagement tier from raw counts.
        Called by unified_profile_builder.py after populating engagement counts.
        """
        days_since = 999 if self.last_app_interaction_days is None else self.last_app_interaction_days
        if days_since >= 14:
            return "churned"
        if days_since >= 7:
            return "at_risk"
        sessions = self.sessions_last7 or 0
        reads = self.morning_read_rate_30d or 0.0
        if sessions >= 5 and reads >= 0.8:
            return "high"
        if sessions >= 2 or reads >= 0.5:
            return "medium"
        return "low"

    def compute_trend(
        self,
        prev_sessions_last7: int = 0,
        prev_morning_read_rate: Optional[float] = None,
    ) -> str:
        curr_score = (self.sessions_last7 or 0) + (self.morning_read_rate_30d or 0) * 5
        prev_score = prev_sessions_last7 + (prev_morning_read_rate or 0) * 5
        if curr_score > prev_score + 0.5:
            return "improving"
        if curr_score < prev_score - 0.5:
            return "declining"
        return "stable"


@dataclass
class CoachRelationship:
    preferred_tone:        Optional[str]   = None   # "compassion"|"push"|"celebrate"|"warn"
    nudge_response_rate:   Optional[float] = None   # 0–1 all-time
    best_nudge_window:     Optional[str]   = None   # "HH:MM"
    last_insight_delivered: Optional[str] = None


@dataclass
class UserFactRecord:
    """
    A single durable fact extracted from conversation.
    Maps to the user_facts DB table.
    """
    fact_id:    Optional[str]   = None
    category:   str             = "preference"
    fact_text:  str             = ""
    fact_key:   Optional[str]   = None
    fact_value: Optional[str]   = None
    polarity:   str             = "neutral"   # "positive"|"negative"|"neutral"
    confidence: float           = 0.5
    ts:         Optional[datetime] = None
    user_confirmed: bool        = False


@dataclass
class PlanItem:
    """One item in the Layer 2 LLM-generated plan."""
    slug:         str
    priority:     str             # "must_do"|"recommended"|"optional"
    duration_min: int
    reason:       str             # human-readable coaching reason (references scores/traits)


@dataclass
class UnifiedProfile:
    """
    The complete persisted personality model for one user.

    One instance per user — rebuilt nightly, read by every coach call.
    Fields with None mean insufficient data (< minimum events threshold).
    """
    # ── Identity ──────────────────────────────────────────────────────────────
    user_id:             str
    archetype_primary:   Optional[str]   = None
    archetype_secondary: Optional[str]   = None
    training_level:      int             = 1
    days_active:         int             = 0

    # ── Domain summaries ──────────────────────────────────────────────────────
    physio:     PhysiologicalTraits   = field(default_factory=PhysiologicalTraits)
    psych:      PsychologicalTraits   = field(default_factory=PsychologicalTraits)
    behaviour:  BehaviouralPreferences = field(default_factory=BehaviouralPreferences)
    engagement: EngagementProfile     = field(default_factory=EngagementProfile)
    coach_rel:  CoachRelationship     = field(default_factory=CoachRelationship)

    # ── Conversation facts (top-N by confidence) ──────────────────────────────
    facts: list[UserFactRecord] = field(default_factory=list)

    # ── Layer 1 — Narrative (written by nightly_analyst.py) ───────────────────
    coach_narrative:    Optional[str] = None
    previous_narrative: Optional[str] = None
    narrative_version:  int           = 1

    # ── Layer 2 — Plan (written by nightly_analyst.py) ────────────────────────
    suggested_plan:     list[PlanItem] = field(default_factory=list)
    plan_for_date:      Optional[date] = None
    plan_guardrail_notes: list[str]   = field(default_factory=list)

    # ── Metadata ──────────────────────────────────────────────────────────────
    data_confidence:  float            = 0.0
    last_computed_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        """Serialize to plain dict for JSON storage / API response."""
        return {
            "user_id":             self.user_id,
            "archetype_primary":   self.archetype_primary,
            "archetype_secondary": self.archetype_secondary,
            "training_level":      self.training_level,
            "days_active":         self.days_active,
            "physio": {
                "prf_bpm":                   self.physio.prf_bpm,
                "prf_status":                self.physio.prf_status,
                "coherence_trainability":    self.physio.coherence_trainability,
                "recovery_arc_speed":        self.physio.recovery_arc_speed,
                "stress_peak_pattern":       self.physio.stress_peak_pattern,
                "sleep_recovery_efficiency": self.physio.sleep_recovery_efficiency,
            },
            "psych": {
                "social_energy_type":      self.psych.social_energy_type,
                "anxiety_sensitivity":     self.psych.anxiety_sensitivity,
                "top_anxiety_triggers":    self.psych.top_anxiety_triggers,
                "primary_recovery_style":  self.psych.primary_recovery_style,
                "discipline_index":        self.psych.discipline_index,
                "streak_current":          self.psych.streak_current,
                "mood_baseline":           self.psych.mood_baseline,
                "interoception_alignment": self.psych.interoception_alignment,
            },
            "behaviour": {
                "top_calming_activities": self.behaviour.top_calming_activities,
                "top_stress_activities":  self.behaviour.top_stress_activities,
                "movement_enjoyed":       self.behaviour.movement_enjoyed,
                "decompress_via":         self.behaviour.decompress_via,
            },
            "engagement": {
                "band_days_worn_last7":      self.engagement.band_days_worn_last7,
                "band_days_worn_last30":     self.engagement.band_days_worn_last30,
                "morning_read_streak":       self.engagement.morning_read_streak,
                "morning_read_rate_30d":     self.engagement.morning_read_rate_30d,
                "sessions_last7":            self.engagement.sessions_last7,
                "sessions_last30":           self.engagement.sessions_last30,
                "conversations_last7":       self.engagement.conversations_last7,
                "nudge_response_rate_30d":   self.engagement.nudge_response_rate_30d,
                "last_app_interaction_days": self.engagement.last_app_interaction_days,
                "engagement_tier":           self.engagement.engagement_tier,
                "engagement_trend":          self.engagement.engagement_trend,
            },
            "coach_relationship": {
                "preferred_tone":         self.coach_rel.preferred_tone,
                "nudge_response_rate":    self.coach_rel.nudge_response_rate,
                "best_nudge_window":      self.coach_rel.best_nudge_window,
                "last_insight_delivered": self.coach_rel.last_insight_delivered,
            },
            "facts": [
                {
                    "category":   f.category,
                    "fact_text":  f.fact_text,
                    "polarity":   f.polarity,
                    "confidence": f.confidence,
                    "confirmed":  f.user_confirmed,
                }
                for f in self.facts
            ],
            "coach_narrative":      self.coach_narrative,
            "narrative_version":    self.narrative_version,
            "suggested_plan":       [
                {
                    "slug":         p.slug,
                    "priority":     p.priority,
                    "duration_min": p.duration_min,
                    "reason":       p.reason,
                }
                for p in self.suggested_plan
            ],
            "plan_for_date":        self.plan_for_date.isoformat() if self.plan_for_date else None,
            "plan_guardrail_notes": self.plan_guardrail_notes,
            "data_confidence":      self.data_confidence,
            "last_computed_at":     self.last_computed_at.isoformat() if self.last_computed_at else None,
        }
