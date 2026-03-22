"""
api/services/profile_service.py

Async DB wrapper for the Unified User Profile layer.

Responsibilities
----------------
  load_unified_profile  — load UserUnifiedProfile row → UnifiedProfile dataclass
  save_unified_profile  — upsert UserUnifiedProfile from UnifiedProfile dataclass
  rebuild_unified_profile — full rebuild: fetch all domain data → build → save
  log_fact              — insert/update a UserFact row
  load_facts            — load UserFact rows for a user
  bump_fact_confidence  — increment confidence on re-mention
  compute_engagement_counts — compute engagement metrics from DB for builder

All functions take a SQLAlchemy AsyncSession and a UUID user_id.
"""

from __future__ import annotations

import logging
import uuid as uuid_mod
from datetime import UTC, date, datetime, timedelta
from typing import Any, Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

import api.db.schema as db
from profile.profile_schema import (
    UnifiedProfile,
    PhysiologicalTraits,
    PsychologicalTraits,
    BehaviouralPreferences,
    EngagementProfile,
    CoachRelationship,
    UserFactRecord,
    PlanItem,
)
from profile.unified_profile_builder import build_unified_profile
from profile.fact_extractor import ExtractedFact

log = logging.getLogger(__name__)


# ── Load / Save ───────────────────────────────────────────────────────────────

async def load_unified_profile(
    session: AsyncSession,
    user_id: uuid_mod.UUID,
) -> Optional[UnifiedProfile]:
    """Load the persisted UnifiedProfile for a user. Returns None if not yet built."""
    row = await _get_uup_row(session, user_id)
    if row is None:
        return None
    return _row_to_profile(row, str(user_id))


async def save_unified_profile(
    session: AsyncSession,
    user_id: uuid_mod.UUID,
    profile: UnifiedProfile,
) -> None:
    """Upsert UserUnifiedProfile from a UnifiedProfile dataclass."""
    row = await _get_uup_row(session, user_id)
    now = datetime.now(UTC)

    plan_json = [
        {
            "slug":         p.slug,
            "priority":     p.priority,
            "duration_min": p.duration_min,
            "reason":       p.reason,
        }
        for p in profile.suggested_plan
    ]

    fields: dict[str, Any] = {
        "narrative_version":        profile.narrative_version,
        "coach_narrative":          profile.coach_narrative,
        "previous_narrative":       profile.previous_narrative,
        "archetype_primary":        profile.archetype_primary,
        "archetype_secondary":      profile.archetype_secondary,
        "training_level":           profile.training_level,
        "days_active":              profile.days_active,
        # Physio
        "prf_bpm":                  profile.physio.prf_bpm,
        "prf_status":               profile.physio.prf_status,
        "coherence_trainability":   profile.physio.coherence_trainability,
        "recovery_arc_speed":       profile.physio.recovery_arc_speed,
        "stress_peak_pattern":      profile.physio.stress_peak_pattern,
        "sleep_recovery_efficiency": profile.physio.sleep_recovery_efficiency,
        # Psych
        "social_energy_type":       profile.psych.social_energy_type,
        "anxiety_sensitivity":      profile.psych.anxiety_sensitivity,
        "top_anxiety_triggers":     profile.psych.top_anxiety_triggers,
        "primary_recovery_style":   profile.psych.primary_recovery_style,
        "discipline_index":         profile.psych.discipline_index,
        "streak_current":           profile.psych.streak_current,
        "mood_baseline":            profile.psych.mood_baseline,
        "interoception_alignment":  profile.psych.interoception_alignment,
        # Behaviour
        "top_calming_activities":   profile.behaviour.top_calming_activities,
        "top_stress_activities":    profile.behaviour.top_stress_activities,
        "habits_summary": {
            "movement_enjoyed": profile.behaviour.movement_enjoyed,
            "decompress_via":   profile.behaviour.decompress_via,
            "stress_drivers":   profile.behaviour.stress_drivers,
            "alcohol":          profile.behaviour.alcohol,
            "caffeine":         profile.behaviour.caffeine,
        },
        # Engagement
        "band_days_worn_last7":     profile.engagement.band_days_worn_last7,
        "band_days_worn_last30":    profile.engagement.band_days_worn_last30,
        "morning_read_streak":      profile.engagement.morning_read_streak,
        "morning_read_rate_30d":    profile.engagement.morning_read_rate_30d,
        "sessions_last7":           profile.engagement.sessions_last7,
        "sessions_last30":          profile.engagement.sessions_last30,
        "conversations_last7":      profile.engagement.conversations_last7,
        "nudge_response_rate_30d":  profile.engagement.nudge_response_rate_30d,
        "last_app_interaction_days": profile.engagement.last_app_interaction_days,
        "engagement_tier":          profile.engagement.engagement_tier,
        "engagement_trend":         profile.engagement.engagement_trend,
        # Coach relationship
        "preferred_tone":           profile.coach_rel.preferred_tone,
        "nudge_response_rate":      profile.coach_rel.nudge_response_rate,
        "best_nudge_window":        profile.coach_rel.best_nudge_window,
        "last_insight_delivered":   profile.coach_rel.last_insight_delivered,
        # Layer 2
        "suggested_plan_json":      plan_json,
        "plan_generated_for_date":  datetime.combine(profile.plan_for_date, datetime.min.time(), tzinfo=UTC) if profile.plan_for_date else None,
        "plan_guardrail_notes":     profile.plan_guardrail_notes,
        # Metadata
        "data_confidence":          profile.data_confidence,
        "last_computed_at":         now,
    }

    if row is None:
        new_row = db.UserUnifiedProfile(
            id=uuid_mod.uuid4(),
            user_id=user_id,
            **fields,
        )
        session.add(new_row)
    else:
        for k, v in fields.items():
            setattr(row, k, v)

    await session.commit()
    log.info("unified_profile_saved user=%s v=%d", user_id, profile.narrative_version)


# ── Rebuild ───────────────────────────────────────────────────────────────────

async def rebuild_unified_profile(
    session: AsyncSession,
    user_id: uuid_mod.UUID,
    *,
    llm_client: Optional[Any] = None,
    net_balance: Optional[float] = None,
    stress_score: Optional[int] = None,
    recovery_score: Optional[int] = None,
    available_slugs: Optional[list[str]] = None,
    assessment: Optional[Any] = None,
) -> UnifiedProfile:
    """
    Full nightly rebuild pipeline:
      1. Fetch all domain data from DB
      2. Build UnifiedProfile via unified_profile_builder
      3. Run Layer 1 narrative (LLM or fallback)
      4. Run Layer 2 plan (LLM or fallback)
      5. Validate plan via guardrails
      6. Save to DB

    Returns the fully-built UnifiedProfile.
    """
    from profile.nightly_analyst import run_layer1_narrative, run_layer2_plan
    from profile.plan_guardrails import validate_plan
    from tagging.activity_catalog import CATALOG

    # -- Fetch domain data --
    user_row      = await _fetch_user_row(session, user_id)
    pm_row        = await _fetch_personal_model(session, user_id)
    psych_row     = await _fetch_psych_profile(session, user_id)
    habits_row    = await _fetch_habits(session, user_id)
    tag_model_row = await _fetch_tag_model(session, user_id)
    eng_counts    = await compute_engagement_counts(session, user_id)
    reaction_rows = await _fetch_coach_reactions(session, user_id)
    fact_rows     = await _load_fact_rows(session, user_id)

    # -- Get previous narrative for delta section --
    prev_row = await _get_uup_row(session, user_id)
    prev_narrative = prev_row.coach_narrative if prev_row else None
    prev_version   = int(prev_row.narrative_version or 1) if prev_row else 1

    # -- Build structured profile --
    profile = build_unified_profile(
        user_row=user_row,
        personal_model=pm_row,
        psych_profile=psych_row,
        habits=habits_row,
        tag_model=tag_model_row,
        engagement_counts=eng_counts,
        coach_reaction_rows=reaction_rows,
        facts=fact_rows,
    )
    profile.previous_narrative = prev_narrative
    profile.narrative_version  = prev_version + 1

    # -- Layer 1: narrative --
    profile = run_layer1_narrative(profile, llm_client=llm_client)

    # -- Layer 2: plan --
    slugs = available_slugs or list(CATALOG.keys())
    profile = run_layer2_plan(
        profile,
        llm_client=llm_client,
        net_balance=net_balance,
        stress_score=stress_score,
        recovery_score=recovery_score,
        available_slugs=slugs,
        adherence=assessment.adherence_7d if assessment is not None else None,
        assessment_note=assessment.summary_note if assessment is not None else None,
    )

    # -- Layer 3: guardrails --
    validated = validate_plan(
        profile.suggested_plan,
        profile,
        net_balance=net_balance,
        stress_score=stress_score,
        recovery_score=recovery_score,
    )
    profile.suggested_plan      = validated.items
    profile.plan_guardrail_notes = validated.guardrail_notes

    # -- Save --
    await save_unified_profile(session, user_id, profile)
    return profile


# ── Facts ─────────────────────────────────────────────────────────────────────

async def log_fact(
    session: AsyncSession,
    user_id: uuid_mod.UUID,
    fact: ExtractedFact,
    *,
    source_conversation_id: Optional[uuid_mod.UUID] = None,
) -> str:
    """Insert a new UserFact row. Returns the row id as string."""
    row = db.UserFact(
        id=uuid_mod.uuid4(),
        user_id=user_id,
        category=fact.category,
        fact_text=fact.fact_text[:200],
        fact_key=fact.fact_key,
        fact_value=fact.fact_value,
        polarity=fact.polarity,
        confidence=fact.confidence,
        source_conversation_id=source_conversation_id,
    )
    session.add(row)
    await session.commit()
    return str(row.id)


async def bump_fact_confidence(
    session: AsyncSession,
    fact_id: uuid_mod.UUID,
    delta: float = 0.2,
) -> None:
    """Increment confidence on an existing fact (re-mention). Capped at 1.0."""
    result = await session.execute(
        select(db.UserFact).where(db.UserFact.id == fact_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return
    row.confidence = min(1.0, round(row.confidence + delta, 3))
    row.last_confirmed_at = datetime.now(UTC)
    await session.commit()


async def load_facts(
    session: AsyncSession,
    user_id: uuid_mod.UUID,
    *,
    min_confidence: float = 0.3,
) -> list[UserFactRecord]:
    """Load UserFact rows above confidence threshold, sorted by confidence desc."""
    result = await session.execute(
        select(db.UserFact)
        .where(
            and_(
                db.UserFact.user_id == user_id,
                db.UserFact.confidence >= min_confidence,
            )
        )
        .order_by(db.UserFact.confidence.desc())
        .limit(20)
    )
    rows = result.scalars().all()
    return [
        UserFactRecord(
            fact_id=str(r.id),
            category=r.category,
            fact_text=r.fact_text,
            fact_key=r.fact_key,
            fact_value=r.fact_value,
            polarity=r.polarity,
            confidence=r.confidence,
            ts=r.created_at,
            user_confirmed=bool(r.user_confirmed),
        )
        for r in rows
    ]


# ── Engagement counts ─────────────────────────────────────────────────────────

async def compute_engagement_counts(
    session: AsyncSession,
    user_id: uuid_mod.UUID,
) -> dict:
    """
    Compute all engagement metrics from DB.
    Returns a dict matching the engagement_counts schema expected by
    unified_profile_builder.build_unified_profile().
    """
    now      = datetime.now(UTC)
    d7_ago   = now - timedelta(days=7)
    d30_ago  = now - timedelta(days=30)

    # Sessions last 7 / 30 days
    res = await session.execute(
        select(func.count(db.Session.id)).where(
            and_(db.Session.user_id == user_id, db.Session.started_at >= d7_ago)
        )
    )
    sessions_last7 = res.scalar_one() or 0

    res = await session.execute(
        select(func.count(db.Session.id)).where(
            and_(db.Session.user_id == user_id, db.Session.started_at >= d30_ago)
        )
    )
    sessions_last30 = res.scalar_one() or 0

    # Conversations last 7 days
    res = await session.execute(
        select(func.count(db.ConversationEvent.id)).where(
            and_(
                db.ConversationEvent.user_id == user_id,
                db.ConversationEvent.ts >= d7_ago,
                db.ConversationEvent.role == "user",
            )
        )
    )
    conversations_last7 = res.scalar_one() or 0

    # Morning reads last 30 days
    res = await session.execute(
        select(func.count(db.MorningRead.id)).where(
            and_(db.MorningRead.user_id == user_id, db.MorningRead.read_date >= d30_ago)
        )
    )
    morning_reads_last30 = res.scalar_one() or 0

    # Morning reads streak — consecutive days up to today with a morning read
    streak = await _compute_morning_read_streak(session, user_id, now)

    # Band days worn = days with at least one valid background_window
    res = await session.execute(
        select(func.count(func.distinct(
            func.date_trunc("day", db.BackgroundWindow.window_start)
        ))).where(
            and_(
                db.BackgroundWindow.user_id == user_id,
                db.BackgroundWindow.window_start >= d7_ago,
                db.BackgroundWindow.is_valid.is_(True),
            )
        )
    )
    band_days_last7 = res.scalar_one() or 0

    res = await session.execute(
        select(func.count(func.distinct(
            func.date_trunc("day", db.BackgroundWindow.window_start)
        ))).where(
            and_(
                db.BackgroundWindow.user_id == user_id,
                db.BackgroundWindow.window_start >= d30_ago,
                db.BackgroundWindow.is_valid.is_(True),
            )
        )
    )
    band_days_last30 = res.scalar_one() or 0

    # Nudge response rate (helpful / total with reaction, last 30 days)
    res = await session.execute(
        select(func.count(db.CoachMessage.id)).where(
            and_(
                db.CoachMessage.user_id == user_id,
                db.CoachMessage.created_at >= d30_ago,
                db.CoachMessage.user_reaction.isnot(None),
            )
        )
    )
    nudge_total_30d = res.scalar_one() or 0

    res = await session.execute(
        select(func.count(db.CoachMessage.id)).where(
            and_(
                db.CoachMessage.user_id == user_id,
                db.CoachMessage.created_at >= d30_ago,
                db.CoachMessage.user_reaction == "helpful",
            )
        )
    )
    nudge_helpful_30d = res.scalar_one() or 0

    # All-time nudge counts
    res = await session.execute(
        select(func.count(db.CoachMessage.id)).where(
            and_(
                db.CoachMessage.user_id == user_id,
                db.CoachMessage.user_reaction.isnot(None),
            )
        )
    )
    nudge_total_count = res.scalar_one() or 0

    res = await session.execute(
        select(func.count(db.CoachMessage.id)).where(
            and_(
                db.CoachMessage.user_id == user_id,
                db.CoachMessage.user_reaction == "helpful",
            )
        )
    )
    nudge_helpful_count = res.scalar_one() or 0

    # Days since last interaction (session OR conversation turn OR morning read)
    last_session_res = await session.execute(
        select(func.max(db.Session.started_at)).where(db.Session.user_id == user_id)
    )
    last_session = last_session_res.scalar_one()

    last_conv_res = await session.execute(
        select(func.max(db.ConversationEvent.ts)).where(
            and_(db.ConversationEvent.user_id == user_id, db.ConversationEvent.role == "user")
        )
    )
    last_conv = last_conv_res.scalar_one()

    last_read_res = await session.execute(
        select(func.max(db.MorningRead.read_date)).where(db.MorningRead.user_id == user_id)
    )
    last_read = last_read_res.scalar_one()

    candidates = [t for t in [last_session, last_conv, last_read] if t is not None]
    last_interaction_days: Optional[int] = None
    if candidates:
        latest = max(candidates)
        if latest.tzinfo is None:
            latest = latest.replace(tzinfo=UTC)
        last_interaction_days = (now - latest).days

    return {
        "sessions_last7":      sessions_last7,
        "sessions_last30":     sessions_last30,
        "conversations_last7": conversations_last7,
        "morning_reads_last30": morning_reads_last30,
        "morning_reads_streak": streak,
        "band_days_last7":     band_days_last7,
        "band_days_last30":    band_days_last30,
        "nudge_total_30d":     nudge_total_30d,
        "nudge_helpful_30d":   nudge_helpful_30d,
        "nudge_total_count":   nudge_total_count,
        "nudge_helpful_count": nudge_helpful_count,
        "last_interaction_days": last_interaction_days,
    }


# ── Private helpers ───────────────────────────────────────────────────────────

async def _get_uup_row(
    session: AsyncSession,
    user_id: uuid_mod.UUID,
) -> Optional[db.UserUnifiedProfile]:
    result = await session.execute(
        select(db.UserUnifiedProfile).where(db.UserUnifiedProfile.user_id == user_id)
    )
    return result.scalar_one_or_none()


def _row_to_profile(row: db.UserUnifiedProfile, user_id: str) -> UnifiedProfile:
    """Convert ORM row to UnifiedProfile dataclass."""
    hs = row.habits_summary or {}
    plan_items = []
    for p in (row.suggested_plan_json or []):
        plan_items.append(PlanItem(
            slug=p.get("slug", ""),
            priority=p.get("priority", "recommended"),
            duration_min=int(p.get("duration_min", 15)),
            reason=p.get("reason", ""),
        ))

    plan_date: Optional[date] = None
    if row.plan_generated_for_date:
        plan_date = row.plan_generated_for_date.date() if hasattr(row.plan_generated_for_date, "date") else None

    return UnifiedProfile(
        user_id=user_id,
        archetype_primary=row.archetype_primary,
        archetype_secondary=row.archetype_secondary,
        training_level=int(row.training_level or 1),
        days_active=int(row.days_active or 0),
        physio=PhysiologicalTraits(
            prf_bpm=row.prf_bpm,
            prf_status=row.prf_status,
            coherence_trainability=row.coherence_trainability,
            recovery_arc_speed=row.recovery_arc_speed,
            stress_peak_pattern=row.stress_peak_pattern,
            sleep_recovery_efficiency=row.sleep_recovery_efficiency,
        ),
        psych=PsychologicalTraits(
            social_energy_type=row.social_energy_type,
            anxiety_sensitivity=row.anxiety_sensitivity,
            top_anxiety_triggers=row.top_anxiety_triggers or [],
            primary_recovery_style=row.primary_recovery_style,
            discipline_index=row.discipline_index,
            streak_current=int(row.streak_current or 0),
            mood_baseline=row.mood_baseline,
            interoception_alignment=row.interoception_alignment,
        ),
        behaviour=BehaviouralPreferences(
            top_calming_activities=row.top_calming_activities or [],
            top_stress_activities=row.top_stress_activities or [],
            movement_enjoyed=hs.get("movement_enjoyed") or [],
            decompress_via=hs.get("decompress_via") or [],
            stress_drivers=hs.get("stress_drivers") or [],
            alcohol=hs.get("alcohol"),
            caffeine=hs.get("caffeine"),
        ),
        engagement=EngagementProfile(
            band_days_worn_last7=row.band_days_worn_last7,
            band_days_worn_last30=row.band_days_worn_last30,
            morning_read_streak=int(row.morning_read_streak or 0),
            morning_read_rate_30d=row.morning_read_rate_30d,
            sessions_last7=int(row.sessions_last7 or 0),
            sessions_last30=int(row.sessions_last30 or 0),
            conversations_last7=int(row.conversations_last7 or 0),
            nudge_response_rate_30d=row.nudge_response_rate_30d,
            last_app_interaction_days=row.last_app_interaction_days,
            engagement_tier=row.engagement_tier,
            engagement_trend=row.engagement_trend,
        ),
        coach_rel=CoachRelationship(
            preferred_tone=row.preferred_tone,
            nudge_response_rate=row.nudge_response_rate,
            best_nudge_window=row.best_nudge_window,
            last_insight_delivered=row.last_insight_delivered,
        ),
        coach_narrative=row.coach_narrative,
        previous_narrative=row.previous_narrative,
        narrative_version=int(row.narrative_version or 1),
        suggested_plan=plan_items,
        plan_for_date=plan_date,
        plan_guardrail_notes=row.plan_guardrail_notes or [],
        data_confidence=float(row.data_confidence or 0.0),
        last_computed_at=row.last_computed_at,
    )


async def _fetch_user_row(session: AsyncSession, user_id: uuid_mod.UUID) -> dict:
    result = await session.execute(select(db.User).where(db.User.id == user_id))
    row = result.scalar_one_or_none()
    if row is None:
        return {"id": str(user_id)}
    return {
        "id":                  str(row.id),
        "archetype_primary":   row.archetype_primary,
        "archetype_secondary": row.archetype_secondary,
        "training_level":      row.training_level,
        "created_at":          row.created_at,
    }


async def _fetch_personal_model(session: AsyncSession, user_id: uuid_mod.UUID) -> dict:
    result = await session.execute(
        select(db.PersonalModel).where(db.PersonalModel.user_id == user_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return {}
    return {
        "prf_bpm":                    row.prf_bpm,
        "prf_status":                 row.prf_status,
        "coherence_trainability":     row.coherence_trainability,
        "recovery_arc_mean_hours":    row.recovery_arc_mean_hours,
        "stress_peak_day":            row.stress_peak_day,
        "stress_peak_hour":           row.stress_peak_hour,
        "sleep_recovery_efficiency":  row.sleep_recovery_efficiency,
        "compliance_best_window":     row.compliance_best_window,
        "natural_elevators":          row.natural_elevators,
        "coherence_drains":           row.coherence_drains,
    }


async def _fetch_psych_profile(session: AsyncSession, user_id: uuid_mod.UUID) -> dict:
    result = await session.execute(
        select(db.UserPsychProfile).where(db.UserPsychProfile.user_id == user_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return {}
    return {
        "social_energy_type":       row.social_energy_type,
        "anxiety_sensitivity":      row.anxiety_sensitivity,
        "top_anxiety_triggers":     row.top_anxiety_triggers,
        "top_calming_activities":   row.top_calming_activities,
        "top_stress_activities":    row.top_stress_activities,
        "primary_recovery_style":   row.primary_recovery_style,
        "discipline_index":         row.discipline_index,
        "streak_current":           row.streak_current,
        "mood_baseline":            row.mood_baseline,
        "interoception_alignment":  row.interoception_alignment,
    }


async def _fetch_habits(session: AsyncSession, user_id: uuid_mod.UUID) -> dict:
    result = await session.execute(
        select(db.UserHabits).where(db.UserHabits.user_id == user_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return {}
    return {
        "movement_enjoyed":  row.movement_enjoyed or [],
        "decompress_via":    row.decompress_via or [],
        "stress_drivers":    row.stress_drivers or [],
        "alcohol":           row.alcohol,
        "caffeine":          row.caffeine,
        "sleep_schedule":    row.sleep_schedule,
    }


async def _fetch_tag_model(session: AsyncSession, user_id: uuid_mod.UUID) -> dict:
    result = await session.execute(
        select(db.TagPatternModel).where(db.TagPatternModel.user_id == user_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return {}
    return {
        "model_json":            row.model_json or {},
        "sport_stressor_slugs":  row.sport_stressor_slugs or [],
    }


async def _fetch_coach_reactions(
    session: AsyncSession, user_id: uuid_mod.UUID
) -> list[dict]:
    result = await session.execute(
        select(db.CoachMessage)
        .where(
            and_(
                db.CoachMessage.user_id == user_id,
                db.CoachMessage.user_reaction.isnot(None),
            )
        )
        .order_by(db.CoachMessage.created_at.desc())
        .limit(50)
    )
    rows = result.scalars().all()
    return [
        {
            "tone":          r.tone,
            "user_reaction": r.user_reaction,
            "summary":       r.summary,
            "created_at":    r.created_at,
        }
        for r in rows
    ]


async def _load_fact_rows(
    session: AsyncSession,
    user_id: uuid_mod.UUID,
) -> list[dict]:
    result = await session.execute(
        select(db.UserFact)
        .where(db.UserFact.user_id == user_id)
        .order_by(db.UserFact.confidence.desc())
        .limit(20)
    )
    rows = result.scalars().all()
    return [
        {
            "id":            str(r.id),
            "category":      r.category,
            "fact_text":     r.fact_text,
            "fact_key":      r.fact_key,
            "fact_value":    r.fact_value,
            "polarity":      r.polarity,
            "confidence":    r.confidence,
            "user_confirmed": r.user_confirmed,
        }
        for r in rows
    ]


async def _compute_morning_read_streak(
    session: AsyncSession,
    user_id: uuid_mod.UUID,
    now: datetime,
) -> int:
    """Count consecutive days with a morning read, going backwards from today."""
    result = await session.execute(
        select(db.MorningRead.read_date)
        .where(db.MorningRead.user_id == user_id)
        .order_by(db.MorningRead.read_date.desc())
        .limit(60)
    )
    read_dates = set()
    for (rd,) in result.all():
        if rd.tzinfo is None:
            rd = rd.replace(tzinfo=UTC)
        read_dates.add(rd.date())

    streak = 0
    check  = now.date()
    while check in read_dates:
        streak += 1
        check  = check - timedelta(days=1)
    return streak
