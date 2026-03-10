"""
psych/psych_profile_builder.py

Computes the PsychProfile from accumulated behavioural data.

All inputs are plain Python dataclasses — no DB handles.
Callers (psych_service.py) load the data and pass it in.

Design rules
------------
1. Never ask the user — every dimension is inferred from data.
2. All scores are expressed in 0–100 readiness/stress/recovery units
   so the coach can reference them without units.
3. Min data thresholds before an inference is made — below threshold
   the dimension is left at "unknown" / 0.0 with low data_confidence.
4. The `coach_insight` string is pre-built here so coach_service can
   inject it directly into CoachContext without further computation.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Optional

from psych.psych_schema import (
    ActivityImpact,
    AnxiestTrigger,
    AnxietyEventRecord,
    MoodRecord,
    PlanAdherence,
    PsychProfile,
    SEVERITY_WEIGHT,
    SocialEvent,
    TaggedActivityRecord,
)

# ── Minimum data thresholds ───────────────────────────────────────────────────

_MIN_SOCIAL_EVENTS    = 3   # n social events before social_energy_type is set
_MIN_ACTIVITY_EVENTS  = 3   # n events before an activity enters top lists
_MIN_ANXIETY_EVENTS   = 2   # n anxiety events before trigger ranking
_MIN_MOOD_LOGS        = 7   # n mood logs before interoception alignment is meaningful
_MIN_PLAN_DAYS        = 7   # n plan days before discipline_index is stable

# ── Recovery style category map ───────────────────────────────────────────────

_CATEGORY_TO_STYLE: dict[str, str] = {
    "movement":            "physical",
    "zenflow_session":     "mindfulness",
    "mindfulness":         "mindfulness",
    "habitual_relaxation": "solo_passive",
    "sleep":               "sleep",
    "recovery_active":     "physical",
}

_SLUG_TO_STYLE_OVERRIDE: dict[str, str] = {
    "social_time":    "social",
    "nature_time":    "nature",
    "cold_shower":    "physical",
    "nap":            "sleep",
    "book_reading":   "solo_passive",
    "music":          "solo_passive",
    "entertainment":  "solo_passive",
}


# ── Public API ────────────────────────────────────────────────────────────────

def build_psych_profile(
    social_events:      list[SocialEvent],
    tagged_activities:  list[TaggedActivityRecord],
    anxiety_events:     list[AnxietyEventRecord],
    mood_records:       list[MoodRecord],
    plan_adherence:     list[PlanAdherence],
    streak_current:     int = 0,
    streak_best:        int = 0,
) -> PsychProfile:
    """
    Compute PsychProfile from all available behavioural data.

    Parameters
    ----------
    social_events
        One entry per tagged social_time window with before/after recovery scores.
    tagged_activities
        All tagged stress/recovery windows with their score deltas.
    anxiety_events
        Structured anxiety trigger records.
    mood_records
        MoodLog entries (most recent first preferred, but any order accepted).
    plan_adherence
        One PlanAdherence per day over the last 28 days.
    streak_current, streak_best
        Loaded from prior psych_profile row or computed externally.
    """

    social_type, social_delta = _infer_social_type(social_events)
    anxiety_sens, top_triggers = _infer_anxiety(anxiety_events, tagged_activities)
    top_calming, top_stress, recovery_style = _infer_activity_map(tagged_activities)
    discipline = _compute_discipline(plan_adherence)
    mood_avg, mood_baseline = _compute_mood_baseline(mood_records)
    interoception = _compute_interoception(mood_records)
    confidence = _compute_confidence(
        social_events, tagged_activities, anxiety_events, mood_records, plan_adherence
    )

    insight = _build_coach_insight(
        social_type=social_type,
        top_triggers=top_triggers,
        top_calming=top_calming,
        discipline=discipline,
        interoception=interoception,
        mood_baseline=mood_baseline,
    )

    return PsychProfile(
        social_energy_type      = social_type,
        social_hrv_delta_avg    = round(social_delta, 1),
        social_event_count      = len(social_events),
        anxiety_sensitivity     = round(anxiety_sens, 3),
        top_anxiety_triggers    = top_triggers,
        top_calming_activities  = top_calming,
        top_stress_activities   = top_stress,
        primary_recovery_style  = recovery_style,
        discipline_index        = round(discipline, 1),
        streak_current          = streak_current,
        streak_best             = streak_best,
        mood_baseline           = mood_baseline,
        mood_score_avg          = round(mood_avg, 2) if mood_avg is not None else None,
        interoception_alignment = interoception,
        data_confidence         = round(confidence, 3),
        coach_insight           = insight,
    )


# ── Social energy inference ───────────────────────────────────────────────────

def _infer_social_type(events: list[SocialEvent]) -> tuple[str, float]:
    """
    Infer social energy type from recovery-score delta during social events.

    Extrovert: mean delta > +3 (social recovers)
    Introvert: mean delta < -3 (social costs energy)
    Ambivert:  -3 <= mean delta <= 3
    """
    if len(events) < _MIN_SOCIAL_EVENTS:
        return "unknown", 0.0

    deltas = [e.recovery_score_after - e.recovery_score_before for e in events]
    mean_delta = sum(deltas) / len(deltas)

    if mean_delta > 4.0:
        social_type = "extrovert"
    elif mean_delta < -4.0:
        social_type = "introvert"
    else:
        social_type = "ambivert"

    return social_type, mean_delta


# ── Anxiety sensitivity + trigger ranking ─────────────────────────────────────

def _infer_anxiety(
    anxiety_events: list[AnxietyEventRecord],
    tagged_activities: list[TaggedActivityRecord],
) -> tuple[float, list[AnxiestTrigger]]:
    """
    Anxiety sensitivity: mean stress_score_at_event across all recorded events.
    Normalised to 0–1 (score / 100).

    Trigger ranking: frequency × avg_severity, normalised to strongest = 1.0.
    """
    # Sensitivity from stress scores at event time
    if anxiety_events:
        mean_stress = sum(e.stress_score_at_event for e in anxiety_events) / len(anxiety_events)
        sensitivity = min(mean_stress / 100.0, 1.0)
    else:
        # Fall back to tagged stress activity suppression
        stress_acts = [a for a in tagged_activities if a.stress_or_recovery == "stress"]
        if stress_acts:
            # negative delta = suppression; flip sign, normalise
            mean_suppression = -sum(min(a.score_delta, 0) for a in stress_acts) / len(stress_acts)
            sensitivity = min(mean_suppression / 30.0, 1.0)   # 30 point drop = max sensitivity
        else:
            sensitivity = 0.0

    # Trigger ranking
    if len(anxiety_events) < _MIN_ANXIETY_EVENTS:
        return sensitivity, []

    bucket: dict[str, list[float]] = defaultdict(list)
    for ev in anxiety_events:
        w = SEVERITY_WEIGHT.get(ev.severity, 0.33)
        bucket[ev.trigger_type].append(w)

    raw: list[tuple[str, int, float]] = []
    for t, weights in bucket.items():
        raw.append((t, len(weights), sum(weights) / len(weights)))

    # Strength = count × avg_severity; normalise to [0, 1]
    max_strength = max(r[1] * r[2] for r in raw) if raw else 1.0
    max_strength = max(max_strength, 1e-9)

    triggers = [
        AnxiestTrigger(
            trigger_type = t,
            count        = n,
            avg_severity = round(avg, 3),
            strength     = round((n * avg) / max_strength, 3),
        )
        for t, n, avg in raw
    ]
    triggers.sort(key=lambda x: x.strength, reverse=True)
    return sensitivity, triggers[:5]


# ── Activity → physiology map ─────────────────────────────────────────────────

def _infer_activity_map(
    tagged_activities: list[TaggedActivityRecord],
) -> tuple[list[ActivityImpact], list[ActivityImpact], str]:
    """
    Build top-calming and top-stress activity lists.
    Primary recovery style = category of the highest-impact recovery activity.
    """
    calming_bucket:  dict[str, list[float]] = defaultdict(list)
    stressing_bucket: dict[str, list[float]] = defaultdict(list)

    for act in tagged_activities:
        if act.stress_or_recovery == "recovery" and act.score_delta > 0:
            calming_bucket[act.slug].append(act.score_delta)
        elif act.stress_or_recovery == "stress" and act.score_delta < 0:
            stressing_bucket[act.slug].append(act.score_delta)

    def _build_list(
        bucket: dict[str, list[float]], top_n: int = 5
    ) -> list[ActivityImpact]:
        impacts = []
        for slug, deltas in bucket.items():
            if len(deltas) < _MIN_ACTIVITY_EVENTS:
                continue
            impacts.append(ActivityImpact(
                slug            = slug,
                count           = len(deltas),
                avg_score_delta = round(sum(deltas) / len(deltas), 1),
            ))
        impacts.sort(key=lambda x: abs(x.avg_score_delta), reverse=True)
        return impacts[:top_n]

    top_calming  = _build_list(calming_bucket)
    top_stressing = _build_list(stressing_bucket)

    # Recovery style from top calming slug
    recovery_style = "unknown"
    if top_calming:
        top_slug = top_calming[0].slug
        recovery_style = _SLUG_TO_STYLE_OVERRIDE.get(
            top_slug,
            _CATEGORY_TO_STYLE.get(
                next(
                    (a.category for a in tagged_activities if a.slug == top_slug),
                    "",
                ),
                "solo_passive",
            ),
        )

    return top_calming, top_stressing, recovery_style


# ── Discipline index ──────────────────────────────────────────────────────────

def _compute_discipline(adherence: list[PlanAdherence]) -> float:
    """
    Discipline index 0–100.

    Base = weighted completion rate (recent days weighted 2×).
    Capped at 100 before streak bonus.
    Returns 0.0 if fewer than _MIN_PLAN_DAYS records.
    """
    if len(adherence) < _MIN_PLAN_DAYS:
        return 0.0

    # Weight recent days more (position in list = chronological, last = most recent)
    n = len(adherence)
    total_weight = 0.0
    total_score  = 0.0
    for i, rec in enumerate(adherence):
        weight = 1.0 + (i / n)   # 1.0 → 2.0 linearly
        if rec.planned > 0:
            completion = rec.completed / rec.planned
        else:
            completion = 1.0   # no plans = no failure
        total_score  += completion * weight
        total_weight += weight

    base = (total_score / total_weight) * 100.0
    return min(round(base, 1), 100.0)


# ── Mood baseline ─────────────────────────────────────────────────────────────

def _compute_mood_baseline(mood_records: list[MoodRecord]) -> tuple[Optional[float], str]:
    """
    Rolling mood average from up to last 14 records.
    Returns (avg float 1–5, label string).
    """
    if not mood_records:
        return None, "unknown"

    recent = mood_records[-14:]
    avg = sum(r.mood_score for r in recent) / len(recent)

    if avg >= 3.8:
        label = "high"
    elif avg >= 2.5:
        label = "moderate"
    else:
        label = "low"

    return avg, label


# ── Interoception alignment ───────────────────────────────────────────────────

def _compute_interoception(mood_records: list[MoodRecord]) -> Optional[float]:
    """
    Pearson r between mood_score and readiness_score_at_log.
    Returns None if fewer than _MIN_MOOD_LOGS records with both values.
    """
    pairs = [
        (r.mood_score, r.readiness_score_at_log)
        for r in mood_records
        if r.readiness_score_at_log is not None
    ]
    if len(pairs) < _MIN_MOOD_LOGS:
        return None

    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    return _pearson_r(xs, ys)


def _pearson_r(xs: list[float], ys: list[float]) -> Optional[float]:
    n = len(xs)
    if n < 2:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    denom = math.sqrt(
        sum((x - mean_x) ** 2 for x in xs) *
        sum((y - mean_y) ** 2 for y in ys)
    )
    if denom < 1e-9:
        return None
    return round(num / denom, 3)


# ── Data confidence ───────────────────────────────────────────────────────────

def _compute_confidence(
    social_events:     list[SocialEvent],
    tagged_activities: list[TaggedActivityRecord],
    anxiety_events:    list[AnxietyEventRecord],
    mood_records:      list[MoodRecord],
    plan_adherence:    list[PlanAdherence],
) -> float:
    """
    Confidence 0–1 based on how much data has been collected across all dimensions.
    Each dimension contributes equally (20%). Full confidence at:
      - social_events >= 10
      - tagged_activities >= 20
      - anxiety_events >= 5
      - mood_records >= 14
      - plan_adherence >= 28
    """
    dims = [
        min(len(social_events)     / 10.0,  1.0),
        min(len(tagged_activities) / 20.0,  1.0),
        min(len(anxiety_events)    / 5.0,   1.0),
        min(len(mood_records)      / 14.0,  1.0),
        min(len(plan_adherence)    / 28.0,  1.0),
    ]
    return sum(dims) / len(dims)


# ── Coach insight builder ─────────────────────────────────────────────────────

def _build_coach_insight(
    social_type:    str,
    top_triggers:   list[AnxiestTrigger],
    top_calming:    list[ActivityImpact],
    discipline:     float,
    interoception:  Optional[float],
    mood_baseline:  str,
) -> str:
    """
    Build one plain-English coaching insight from the most notable signal.
    Expressed purely in behavioural/score terms — no RMSSD, no RSA.
    """
    # Interoception gap is the highest-value insight
    if interoception is not None and interoception < 0.25 and interoception > -1.0:
        return (
            "Your body and how you feel aren't aligned yet — "
            "that gap is where the biggest gains sit."
        )

    # Top anxiety trigger with a calming solution
    if top_triggers and top_calming:
        trigger_label = top_triggers[0].trigger_type.replace("_", " ")
        calm_slug     = top_calming[0].slug.replace("_", " ")
        lift          = abs(top_calming[0].avg_score_delta)
        return (
            f"Your recovery score rises by ~{lift:.0f} points after {calm_slug} — "
            f"schedule it after {trigger_label} events."
        )

    # Social energy insight
    if social_type == "introvert":
        return (
            "Social events typically cost you recovery points — "
            "protect solo time the day after group activities."
        )
    if social_type == "extrovert":
        return (
            "Social time consistently lifts your recovery score — "
            "use it strategically before high-demand days."
        )

    # Discipline insight
    if discipline > 0 and discipline < 60:
        return (
            f"Discipline index is {discipline:.0f}/100 — "
            "consistency in showing up is the highest-leverage variable right now."
        )

    # Mood baseline
    if mood_baseline == "low":
        return (
            "Mood has been tracking low — "
            "small wins and short sessions matter more than intensity right now."
        )

    return "Keep building the dataset — patterns are starting to emerge."
