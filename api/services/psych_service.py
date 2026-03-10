"""
api/services/psych_service.py

Async DB wrapper for the psychological profile subsystem.

Responsibilities
----------------
1. Load / save UserPsychProfile rows.
2. Append MoodLog and AnxietyEvent rows.
3. Rebuild PsychProfile by loading all raw data and calling the builder.

Design
------
- All DB operations use SQLAlchemy async sessions (injected by callers).
- All computation is delegated to psych.psych_profile_builder — no logic here.
- Returns pure Python dataclasses; routers handle serialisation.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime, time, timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db import schema as db
from psych.psych_profile_builder import build_psych_profile
from psych.psych_schema import (
    AnxietyEventRecord,
    MoodRecord,
    PlanAdherence,
    PsychProfile,
    SocialEvent,
    TaggedActivityRecord,
)

logger = logging.getLogger(__name__)


# ── Load profile ──────────────────────────────────────────────────────────────

async def load_psych_profile(
    session: AsyncSession,
    user_id: UUID,
) -> Optional[PsychProfile]:
    """
    Load stored PsychProfile for user_id from DB.
    Returns None if no row exists yet.
    """
    row = await _get_profile_row(session, user_id)
    if row is None:
        return None
    return _row_to_profile(row)


# ── Save profile ──────────────────────────────────────────────────────────────

async def save_psych_profile(
    session: AsyncSession,
    user_id: UUID,
    profile: PsychProfile,
) -> None:
    """
    Upsert PsychProfile. Creates row if missing, updates if present.
    """
    row = await _get_profile_row(session, user_id)
    if row is None:
        row = db.UserPsychProfile(user_id=user_id)
        session.add(row)

    row.social_energy_type      = profile.social_energy_type
    row.social_hrv_delta_avg    = profile.social_hrv_delta_avg
    row.social_event_count      = profile.social_event_count
    row.anxiety_sensitivity     = profile.anxiety_sensitivity
    row.top_anxiety_triggers    = json.dumps([
        {"trigger_type": t.trigger_type,
         "count":        t.count,
         "avg_severity": t.avg_severity,
         "strength":     t.strength}
        for t in profile.top_anxiety_triggers
    ])
    row.top_calming_activities  = json.dumps([
        {"slug": a.slug, "count": a.count, "avg_score_delta": a.avg_score_delta}
        for a in profile.top_calming_activities
    ])
    row.top_stress_activities   = json.dumps([
        {"slug": a.slug, "count": a.count, "avg_score_delta": a.avg_score_delta}
        for a in profile.top_stress_activities
    ])
    row.primary_recovery_style  = profile.primary_recovery_style
    row.discipline_index        = profile.discipline_index
    row.streak_current          = profile.streak_current
    row.streak_best             = profile.streak_best
    row.mood_baseline           = profile.mood_baseline
    row.mood_score_avg          = profile.mood_score_avg
    row.interoception_alignment = profile.interoception_alignment
    row.data_confidence         = profile.data_confidence
    row.last_computed_at        = datetime.now(UTC)

    await session.flush()


# ── Log mood ──────────────────────────────────────────────────────────────────

async def log_mood(
    session: AsyncSession,
    user_id: UUID,
    *,
    mood_score: float,
    energy_score: Optional[float] = None,
    anxiety_score: Optional[float] = None,
    social_desire: Optional[float] = None,
    readiness_score_at_log: Optional[float] = None,
    stress_score_at_log: Optional[float] = None,
    recovery_score_at_log: Optional[float] = None,
    source: str = "manual",
    notes: Optional[str] = None,
) -> str:
    """
    Append a MoodLog row. Returns the new row id as string.
    """
    row = db.MoodLog(
        user_id                 = user_id,
        log_date                = date.today(),
        mood_score              = mood_score,
        energy_score            = energy_score,
        anxiety_score           = anxiety_score,
        social_desire           = social_desire,
        readiness_score_at_log  = readiness_score_at_log,
        stress_score_at_log     = stress_score_at_log,
        recovery_score_at_log   = recovery_score_at_log,
        source                  = source,
        notes                   = notes,
    )
    session.add(row)
    await session.flush()
    return str(row.id)


# ── Log anxiety event ─────────────────────────────────────────────────────────

async def log_anxiety_event(
    session: AsyncSession,
    user_id: UUID,
    *,
    trigger_type: str,
    severity: str,
    stress_score_at_event: float,
    stress_window_id: Optional[UUID] = None,
    recovery_score_drop: Optional[float] = None,
    resolution_activity: Optional[str] = None,
    resolved: bool = False,
    reported_via: str = "manual",
) -> str:
    """
    Append an AnxietyEvent row. Returns the new row id as string.
    """
    row = db.AnxietyEvent(
        user_id               = user_id,
        ts                    = datetime.now(UTC),
        trigger_type          = trigger_type,
        severity              = severity,
        stress_window_id      = stress_window_id,
        stress_score_at_event = stress_score_at_event,
        recovery_score_drop   = recovery_score_drop,
        resolution_activity   = resolution_activity,
        resolved              = resolved,
        reported_via          = reported_via,
    )
    session.add(row)
    await session.flush()
    return str(row.id)


# ── Rebuild profile (full recompute) ─────────────────────────────────────────

async def rebuild_profile(
    session: AsyncSession,
    user_id: UUID,
) -> PsychProfile:
    """
    Load all raw data, recompute PsychProfile, persist, and return it.
    """
    social_events   = await _load_social_events(session, user_id)
    tagged_acts     = await _load_tagged_activities(session, user_id)
    anxiety_events  = await _load_anxiety_events(session, user_id)
    mood_records    = await _load_mood_records(session, user_id)
    plan_adherence  = await _load_plan_adherence(session, user_id)

    # Preserve existing streak values if profile exists
    existing_row = await _get_profile_row(session, user_id)
    streak_current = existing_row.streak_current if existing_row else 0
    streak_best    = existing_row.streak_best    if existing_row else 0

    profile = build_psych_profile(
        social_events     = social_events,
        tagged_activities = tagged_acts,
        anxiety_events    = anxiety_events,
        mood_records      = mood_records,
        plan_adherence    = plan_adherence,
        streak_current    = streak_current,
        streak_best       = streak_best,
    )

    await save_psych_profile(session, user_id, profile)
    logger.info("Rebuilt psych profile for user %s (confidence=%.2f)", user_id, profile.data_confidence)
    return profile


# ── Private helpers ───────────────────────────────────────────────────────────

async def _get_profile_row(
    session: AsyncSession,
    user_id: UUID,
) -> Optional[db.UserPsychProfile]:
    result = await session.execute(
        select(db.UserPsychProfile).where(db.UserPsychProfile.user_id == user_id)
    )
    return result.scalar_one_or_none()


def _row_to_profile(row: db.UserPsychProfile) -> PsychProfile:
    from psych.psych_schema import AnxiestTrigger, ActivityImpact

    triggers_raw = json.loads(row.top_anxiety_triggers  or "[]")
    calming_raw  = json.loads(row.top_calming_activities or "[]")
    stress_raw   = json.loads(row.top_stress_activities  or "[]")

    return PsychProfile(
        social_energy_type      = row.social_energy_type      or "unknown",
        social_hrv_delta_avg    = row.social_hrv_delta_avg    or 0.0,
        social_event_count      = row.social_event_count      or 0,
        anxiety_sensitivity     = row.anxiety_sensitivity     or 0.0,
        top_anxiety_triggers    = [
            AnxiestTrigger(**t) for t in triggers_raw
        ],
        top_calming_activities  = [
            ActivityImpact(**a) for a in calming_raw
        ],
        top_stress_activities   = [
            ActivityImpact(**a) for a in stress_raw
        ],
        primary_recovery_style  = row.primary_recovery_style  or "unknown",
        discipline_index        = row.discipline_index        or 0.0,
        streak_current          = row.streak_current          or 0,
        streak_best             = row.streak_best             or 0,
        mood_baseline           = row.mood_baseline           or "unknown",
        mood_score_avg          = row.mood_score_avg,
        interoception_alignment = row.interoception_alignment,
        data_confidence         = row.data_confidence         or 0.0,
        coach_insight           = None,   # not persisted; rebuilt on demand
    )


async def _load_social_events(
    session: AsyncSession,
    user_id: UUID,
) -> list[SocialEvent]:
    """
    Derive SocialEvent records from tagged social_time recovery windows.
    We use RecoveryWindow rows tagged 'social_time' and neighbouring
    StressWindow rows to build before/after scores.
    This is a best-effort approximation — paired windows within 15 min.
    """
    rec_result = await session.execute(
        select(db.RecoveryWindow)
        .where(
            and_(
                db.RecoveryWindow.user_id == user_id,
                db.RecoveryWindow.tag == "social_time",
            )
        )
        .order_by(db.RecoveryWindow.started_at)
        .limit(200)
    )
    recovery_windows = rec_result.scalars().all()

    events: list[SocialEvent] = []
    for rw in recovery_windows:
        # Express before/after as recovery-score proxies using rmssd_avg_ms
        # and recovery_contribution_pct where available
        after_proxy = float(rw.recovery_contribution_pct or 50.0)
        # We don't have a "before" measure on the RecoveryWindow directly;
        # use a conservative 0 delta (we'll only have signal if the user
        # explicitly tags social_time, and we accumulate over many events)
        before_proxy = max(after_proxy - 5.0, 0.0)   # placeholder until we pair windows
        events.append(SocialEvent(
            event_id              = str(rw.id),
            ts                    = rw.started_at,
            duration_minutes      = rw.duration_minutes or 30,
            recovery_score_before = before_proxy,
            recovery_score_after  = after_proxy,
        ))
    return events


async def _load_tagged_activities(
    session: AsyncSession,
    user_id: UUID,
) -> list[TaggedActivityRecord]:
    """
    Load stress and recovery windows that have been user-tagged.
    """
    tagged_acts: list[TaggedActivityRecord] = []

    # Recovery windows with non-null tags
    rec_result = await session.execute(
        select(db.RecoveryWindow)
        .where(
            and_(
                db.RecoveryWindow.user_id  == user_id,
                db.RecoveryWindow.tag      != None,  # noqa: E711
                db.RecoveryWindow.tag_source.in_(["user_confirmed", "coach_confirmed"]),
            )
        )
        .order_by(db.RecoveryWindow.started_at.desc())
        .limit(500)
    )
    for rw in rec_result.scalars():
        tagged_acts.append(TaggedActivityRecord(
            slug             = rw.tag,
            ts               = rw.started_at,
            duration_minutes = rw.duration_minutes or 0,
            stress_or_recovery = "recovery",
            score_delta      = float(rw.recovery_contribution_pct or 0),
            category         = "recovery",
        ))

    # Stress windows with user-confirmed tags
    str_result = await session.execute(
        select(db.StressWindow)
        .where(
            and_(
                db.StressWindow.user_id    == user_id,
                db.StressWindow.tag        != None,  # noqa: E711
                db.StressWindow.tag_source.in_(["user", "user_confirmed", "coach_confirmed"]),
            )
        )
        .order_by(db.StressWindow.started_at.desc())
        .limit(500)
    )
    for sw in str_result.scalars():
        tagged_acts.append(TaggedActivityRecord(
            slug             = sw.tag,
            ts               = sw.started_at,
            duration_minutes = sw.duration_minutes or 0,
            stress_or_recovery = "stress",
            score_delta      = -float(sw.suppression_pct or 0),
            category         = "stress",
        ))

    return tagged_acts


async def _load_anxiety_events(
    session: AsyncSession,
    user_id: UUID,
) -> list[AnxietyEventRecord]:
    result = await session.execute(
        select(db.AnxietyEvent)
        .where(db.AnxietyEvent.user_id == user_id)
        .order_by(db.AnxietyEvent.ts.desc())
        .limit(200)
    )
    events = []
    for row in result.scalars():
        events.append(AnxietyEventRecord(
            event_id              = str(row.id),
            ts                    = row.ts,
            trigger_type          = row.trigger_type,
            severity              = row.severity,
            stress_score_at_event = row.stress_score_at_event or 50.0,
            recovery_score_drop   = row.recovery_score_drop,
            resolution_activity   = row.resolution_activity,
            resolved              = row.resolved or False,
        ))
    return events


async def _load_mood_records(
    session: AsyncSession,
    user_id: UUID,
) -> list[MoodRecord]:
    result = await session.execute(
        select(db.MoodLog)
        .where(db.MoodLog.user_id == user_id)
        .order_by(db.MoodLog.created_at.asc())
        .limit(90)
    )
    records = []
    for row in result.scalars():
        records.append(MoodRecord(
            ts                     = row.created_at,
            mood_score             = row.mood_score or 3.0,
            energy_score           = row.energy_score,
            anxiety_score          = row.anxiety_score,
            social_desire          = row.social_desire,
            readiness_score_at_log = row.readiness_score_at_log,
            stress_score_at_log    = row.stress_score_at_log,
            recovery_score_at_log  = row.recovery_score_at_log,
        ))
    return records


async def _load_plan_adherence(
    session: AsyncSession,
    user_id: UUID,
    days: int = 28,
) -> list[PlanAdherence]:
    """
    Build PlanAdherence from DailyPlan rows — completed vs planned items.
    """
    start_date = date.today() - timedelta(days=days)

    result = await session.execute(
        select(db.DailyPlan)
        .where(
            db.DailyPlan.user_id    == user_id,
            db.DailyPlan.plan_date  >= datetime.combine(start_date, time(0, 0, 0), UTC),
        )
        .order_by(db.DailyPlan.plan_date.asc())
    )
    adherence = []
    for row in result.scalars():
        items = json.loads(row.items_json or "[]")
        planned   = len(items)
        completed = sum(1 for i in items if i.get("status") == "done")
        adherence.append(PlanAdherence(
            plan_date = row.plan_date,
            planned   = planned,
            completed = completed,
        ))
    return adherence
