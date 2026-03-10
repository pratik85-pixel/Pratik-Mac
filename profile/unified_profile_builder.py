"""
profile/unified_profile_builder.py

Assembles a UnifiedProfile dataclass from domain data.

This module is PURE PYTHON — no DB calls, no LLM calls.
It takes pre-fetched data bags and computes the structured profile.

The nightly_analyst.py calls this first, then enriches the result
with LLM-generated narrative (Layer 1) and suggested plan (Layer 2).

Data bags (all plain Python dicts / lists — fetched by profile_service.py):
  user_row          — User ORM row dict (archetype, training_level, etc.)
  personal_model    — PersonalModel row dict
  psych_profile     — UserPsychProfile row dict
  habits            — UserHabits row dict
  tag_model         — TagPatternModel row dict
  engagement_counts — dict with pre-computed engagement metrics
  coach_reaction_rows— list of CoachMessage dicts (for tone preference)
  facts             — list of UserFact row dicts

Returns a fully-populated UnifiedProfile with data_confidence 0–1.
"""

from __future__ import annotations

import logging
from datetime import datetime, UTC
from typing import Optional

from profile.profile_schema import (
    UnifiedProfile,
    PhysiologicalTraits,
    PsychologicalTraits,
    BehaviouralPreferences,
    EngagementProfile,
    CoachRelationship,
    UserFactRecord,
)

log = logging.getLogger(__name__)

# Minimum data thresholds for a field to be considered "populated"
_MIN_ENGAGEMENT_SESSIONS = 1
_CONFIDENCE_WEIGHTS = {
    "physio":      0.20,
    "psych":       0.25,
    "behaviour":   0.15,
    "engagement":  0.20,
    "coach_rel":   0.10,
    "facts":       0.10,
}


# ── Public API ────────────────────────────────────────────────────────────────

def build_unified_profile(
    *,
    user_row: dict,
    personal_model: Optional[dict] = None,
    psych_profile: Optional[dict] = None,
    habits: Optional[dict] = None,
    tag_model: Optional[dict] = None,
    engagement_counts: Optional[dict] = None,
    coach_reaction_rows: Optional[list[dict]] = None,
    facts: Optional[list[dict]] = None,
) -> UnifiedProfile:
    """
    Build a UnifiedProfile from pre-fetched domain data.

    Parameters
    ----------
    user_row : dict
        Serialised User row — must contain 'id', 'archetype_primary',
        'archetype_secondary', 'training_level', 'created_at'.
    personal_model : dict | None
        Serialised PersonalModel row.
    psych_profile : dict | None
        Serialised UserPsychProfile row.
    habits : dict | None
        Serialised UserHabits row.
    tag_model : dict | None
        Serialised TagPatternModel row.
    engagement_counts : dict | None
        Pre-computed engagement metrics (fetched by profile_service):
          sessions_last7, sessions_last30, conversations_last7,
          morning_reads_last30, morning_reads_streak,
          band_days_last7, band_days_last30,
          nudge_helpful_count, nudge_total_count,
          nudge_helpful_30d, nudge_total_30d,
          last_interaction_days
    coach_reaction_rows : list[dict] | None
        CoachMessage rows with user_reaction populated.
    facts : list[dict] | None
        UserFact rows for this user.

    Returns
    -------
    UnifiedProfile
    """
    uid = str(user_row.get("id", ""))
    pm  = personal_model or {}
    pp  = psych_profile or {}
    hab = habits or {}
    ec  = engagement_counts or {}
    rcr = coach_reaction_rows or []
    fts = facts or []

    # ── Days active ───────────────────────────────────────────────────────────
    created_at = user_row.get("created_at")
    days_active = 0
    if created_at is not None:
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at)
            except ValueError:
                created_at = None
        if created_at is not None:
            now = datetime.now(UTC)
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)
            days_active = max(0, (now - created_at).days)

    # ── Physiological traits ──────────────────────────────────────────────────
    physio = _build_physio(pm)

    # ── Psychological traits ──────────────────────────────────────────────────
    psych = _build_psych(pp)

    # ── Behavioural preferences ───────────────────────────────────────────────
    behaviour = _build_behaviour(hab, pp, tag_model)

    # ── Engagement profile ────────────────────────────────────────────────────
    engagement = _build_engagement(ec)

    # ── Coach relationship ────────────────────────────────────────────────────
    coach_rel = _build_coach_relationship(rcr, pm)

    # ── Conversation facts ────────────────────────────────────────────────────
    fact_records = _build_facts(fts)

    # ── Data confidence ───────────────────────────────────────────────────────
    confidence = _compute_confidence(physio, psych, behaviour, engagement, coach_rel, fact_records)

    return UnifiedProfile(
        user_id=uid,
        archetype_primary=user_row.get("archetype_primary"),
        archetype_secondary=user_row.get("archetype_secondary"),
        training_level=int(user_row.get("training_level") or 1),
        days_active=days_active,
        physio=physio,
        psych=psych,
        behaviour=behaviour,
        engagement=engagement,
        coach_rel=coach_rel,
        facts=fact_records,
        data_confidence=confidence,
        last_computed_at=datetime.now(UTC),
    )


# ── Private helpers ───────────────────────────────────────────────────────────

def _build_physio(pm: dict) -> PhysiologicalTraits:
    arc_hours = pm.get("recovery_arc_mean_hours")
    arc_speed: Optional[str] = None
    if arc_hours is not None:
        if arc_hours < 2.0:
            arc_speed = "fast"
        elif arc_hours < 5.0:
            arc_speed = "normal"
        else:
            arc_speed = "slow"

    # Stress peak pattern as human-readable string
    peak_pattern: Optional[str] = None
    peak_day  = pm.get("stress_peak_day")
    peak_hour = pm.get("stress_peak_hour")
    if peak_day and peak_hour is not None:
        peak_pattern = f"{peak_day} {peak_hour:02d}:00"

    return PhysiologicalTraits(
        prf_bpm=pm.get("prf_bpm"),
        prf_status=pm.get("prf_status"),
        coherence_trainability=pm.get("coherence_trainability"),
        recovery_arc_speed=arc_speed,
        stress_peak_pattern=peak_pattern,
        sleep_recovery_efficiency=pm.get("sleep_recovery_efficiency"),
    )


def _build_psych(pp: dict) -> PsychologicalTraits:
    return PsychologicalTraits(
        social_energy_type=pp.get("social_energy_type"),
        anxiety_sensitivity=pp.get("anxiety_sensitivity"),
        top_anxiety_triggers=pp.get("top_anxiety_triggers") or [],
        primary_recovery_style=pp.get("primary_recovery_style"),
        discipline_index=pp.get("discipline_index"),
        streak_current=int(pp.get("streak_current") or 0),
        mood_baseline=pp.get("mood_baseline"),
        interoception_alignment=pp.get("interoception_alignment"),
    )


def _build_behaviour(
    hab: dict,
    pp: dict,
    tag_model: Optional[dict],
) -> BehaviouralPreferences:
    return BehaviouralPreferences(
        top_calming_activities=pp.get("top_calming_activities") or [],
        top_stress_activities=pp.get("top_stress_activities") or [],
        movement_enjoyed=hab.get("movement_enjoyed") or [],
        decompress_via=hab.get("decompress_via") or [],
        stress_drivers=hab.get("stress_drivers") or [],
        alcohol=hab.get("alcohol"),
        caffeine=hab.get("caffeine"),
        sleep_schedule=hab.get("sleep_schedule"),
    )


def _build_engagement(ec: dict) -> EngagementProfile:
    sessions_last7  = int(ec.get("sessions_last7", 0))
    sessions_last30 = int(ec.get("sessions_last30", 0))
    conv_last7      = int(ec.get("conversations_last7", 0))
    mr_last30       = int(ec.get("morning_reads_last30", 0))
    mr_rate         = round(mr_last30 / 30, 3) if mr_last30 else None
    mr_streak       = int(ec.get("morning_reads_streak", 0))
    band_last7      = ec.get("band_days_last7")
    band_last30     = ec.get("band_days_last30")
    last_days       = ec.get("last_interaction_days")

    nudge_total_30  = int(ec.get("nudge_total_30d", 0))
    nudge_help_30   = int(ec.get("nudge_helpful_30d", 0))
    nudge_rate_30   = round(nudge_help_30 / nudge_total_30, 3) if nudge_total_30 else None

    nudge_total_all = int(ec.get("nudge_total_count", 0))
    nudge_help_all  = int(ec.get("nudge_helpful_count", 0))

    eng = EngagementProfile(
        band_days_worn_last7=band_last7,
        band_days_worn_last30=band_last30,
        morning_read_streak=mr_streak,
        morning_read_rate_30d=mr_rate,
        sessions_last7=sessions_last7,
        sessions_last30=sessions_last30,
        conversations_last7=conv_last7,
        nudge_response_rate_30d=nudge_rate_30,
        last_app_interaction_days=int(last_days) if last_days is not None else None,
    )
    eng.engagement_tier  = eng.compute_tier()
    # Simple trend: more sessions than last week → improving (prev week not stored here yet)
    eng.engagement_trend = "stable"
    return eng


def _build_coach_relationship(
    reactions: list[dict],
    pm: dict,
) -> CoachRelationship:
    if not reactions:
        return CoachRelationship(
            best_nudge_window=pm.get("compliance_best_window"),
        )

    tone_counts: dict[str, int] = {}
    helpful_tones: dict[str, int] = {}
    for row in reactions:
        tone     = row.get("tone")
        reaction = row.get("user_reaction")
        if tone:
            tone_counts[tone] = tone_counts.get(tone, 0) + 1
            if reaction == "helpful":
                helpful_tones[tone] = helpful_tones.get(tone, 0) + 1

    # Preferred tone = highest helpful/sent ratio (min 3 sent)
    best_tone: Optional[str] = None
    best_ratio = -1.0
    for tone, sent in tone_counts.items():
        if sent >= 3:
            ratio = helpful_tones.get(tone, 0) / sent
            if ratio > best_ratio:
                best_ratio = ratio
                best_tone  = tone

    total_reactions = len(reactions)
    helpful_count   = sum(1 for r in reactions if r.get("user_reaction") == "helpful")
    response_rate   = round(helpful_count / total_reactions, 3) if total_reactions else None

    last_insight = (
        reactions[-1].get("summary") if reactions else None
    )

    return CoachRelationship(
        preferred_tone=best_tone,
        nudge_response_rate=response_rate,
        best_nudge_window=pm.get("compliance_best_window"),
        last_insight_delivered=last_insight,
    )


def _build_facts(rows: list[dict]) -> list[UserFactRecord]:
    records = []
    for r in rows:
        records.append(UserFactRecord(
            fact_id=str(r.get("id", "")),
            category=r.get("category", "preference"),
            fact_text=r.get("fact_text", ""),
            fact_key=r.get("fact_key"),
            fact_value=r.get("fact_value"),
            polarity=r.get("polarity", "neutral"),
            confidence=float(r.get("confidence", 0.5)),
            user_confirmed=bool(r.get("user_confirmed", False)),
        ))
    # Sort by confidence descending — top facts surface first in narrative
    records.sort(key=lambda f: f.confidence, reverse=True)
    return records


def _compute_confidence(
    physio:    PhysiologicalTraits,
    psych:     PsychologicalTraits,
    behaviour: BehaviouralPreferences,
    engagement: EngagementProfile,
    coach_rel: CoachRelationship,
    facts:     list[UserFactRecord],
) -> float:
    scores: dict[str, float] = {}

    # Physio: populated if prf_status not None and recovery_arc_speed not None
    p_count = sum([
        physio.prf_status is not None,
        physio.coherence_trainability is not None,
        physio.recovery_arc_speed is not None,
        physio.stress_peak_pattern is not None,
        physio.sleep_recovery_efficiency is not None,
    ])
    scores["physio"] = p_count / 5

    # Psych: populated if social_energy_type and anxiety_sensitivity not None
    ps_count = sum([
        psych.social_energy_type is not None,
        psych.anxiety_sensitivity is not None,
        len(psych.top_anxiety_triggers) > 0,
        psych.primary_recovery_style is not None,
        psych.discipline_index is not None,
        psych.mood_baseline is not None,
        psych.interoception_alignment is not None,
    ])
    scores["psych"] = ps_count / 7

    # Behaviour: populated if top_calming_activities not empty
    b_count = sum([
        len(behaviour.top_calming_activities) > 0,
        len(behaviour.top_stress_activities) > 0,
        len(behaviour.movement_enjoyed) > 0,
        len(behaviour.decompress_via) > 0,
    ])
    scores["behaviour"] = b_count / 4

    # Engagement: some engagement data present
    e_count = sum([
        engagement.sessions_last7 > 0,
        engagement.morning_read_rate_30d is not None,
        engagement.band_days_worn_last7 is not None,
        engagement.engagement_tier is not None,
    ])
    scores["engagement"] = e_count / 4

    # Coach relationship
    scores["coach_rel"] = 1.0 if coach_rel.preferred_tone else 0.0

    # Facts
    scores["facts"] = min(1.0, len(facts) / 5)

    weighted = sum(
        scores.get(k, 0.0) * w
        for k, w in _CONFIDENCE_WEIGHTS.items()
    )
    return round(weighted, 3)
