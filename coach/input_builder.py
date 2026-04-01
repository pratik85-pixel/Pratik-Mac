"""
Layer 1 — CoachInputPacket builder.

This module builds a single deterministic data dump for every LLM call in the
coach system (Layer 2 narrative + all Layer 3 surface prompts).

Contract
---------
* No raw RMSSD values reach the LLM. Wherever RMSSD appears, we convert to
  personal-relative % strings.
* LLM input is assembled from DB rows and returned as structured primitives
  (dicts / lists) so prompt templates can render consistently.
"""

from __future__ import annotations

import asyncio
import math
import uuid as uuid_mod
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

import api.db.schema as db
from coach.text_sanitizer import sanitize_text
from tracking.cycle_boundaries import local_today, product_calendar_timezone


def _sanitize_text(text: Optional[str], *, max_len: int = 200) -> str:
    return sanitize_text(text, max_len=max_len)


def _pct_str(delta_frac: float, *, reference: str) -> str:
    """
    Convert fractional delta to a compact signed string.

    Examples
    --------
    * -0.21 → "-21% below your average"
    * +0.12 → "+12% above your floor"
    """
    abs_pct = abs(delta_frac) * 100.0
    if abs_pct < 1.0:
        return f"at {reference}"
    sign = "-" if delta_frac < 0 else "+"
    above_below = "below" if delta_frac < 0 else "above"
    return f"{sign}{abs_pct:.0f}% {above_below} {reference}"


def _compute_sleep_recovery_score_from_raw(
    raw_recovery_area_sleep: Optional[float],
    ns_capacity_recovery: Optional[float],
) -> Optional[float]:
    """
    Compute sleep recovery 0..100 from stored raw sleep recovery area.

    Daily summarizer uses:
      sleep_score_denominator = log_range * DAILY_CAPACITY_SLEEP_MINUTES
      waking_denominator      = log_range * DAILY_CAPACITY_WAKING_MINUTES
      total recovery denominator (legacy display model) = * 1440

    Because:
      DAILY_CAPACITY_WAKING_MINUTES = 960
      DAILY_CAPACITY_SLEEP_MINUTES  = 480
      and 960/1440 = 2/3, 480/1440 = 1/3

    We can approximate:
      sleep_score_denominator = ns_capacity_recovery / 3
    """
    if raw_recovery_area_sleep is None:
        return None
    if not ns_capacity_recovery or ns_capacity_recovery <= 0:
        return None

    sleep_den = float(ns_capacity_recovery) / 3.0
    if sleep_den <= 0:
        return None

    pct = (float(raw_recovery_area_sleep) / sleep_den) * 100.0
    pct = max(0.0, min(100.0, pct))
    return round(pct, 1)


@dataclass(frozen=True)
class CoachInputPacket:
    """
    Layer 1 packet consumed by Layer 2 (nightly narrative) and Layer 3
    surface prompts.
    """

    user_id: str
    today_local_date: str  # YYYY-MM-DD in product timezone

    # ── Personal model ──────────────────────────────────────────────────────
    personal_model: dict[str, Any] = field(default_factory=dict)

    # ── Daily stress / recovery trajectory (oldest → newest) ──────────────
    daily_trajectory: list[dict[str, Any]] = field(default_factory=list)

    # ── Morning reads (last 7) ──────────────────────────────────────────────
    morning_reads: list[dict[str, Any]] = field(default_factory=list)

    # ── Stress + recovery windows ─────────────────────────────────────────
    stress_windows_48h: dict[str, Any] = field(default_factory=dict)
    recovery_windows_48h: dict[str, Any] = field(default_factory=dict)

    # ── Background bins (last 24h) ─────────────────────────────────────────
    background_bins_24h: list[dict[str, Any]] = field(default_factory=list)

    # ── Lifestyle + subjective signals ─────────────────────────────────────
    habit_events_72h: list[dict[str, Any]] = field(default_factory=list)
    check_ins_7d: list[dict[str, Any]] = field(default_factory=list)
    anxiety_events_14d: list[dict[str, Any]] = field(default_factory=list)
    conversation_events_3d: list[dict[str, Any]] = field(default_factory=list)
    user_facts: list[str] = field(default_factory=list)

    # ── Behavioural patterns from tag model ────────────────────────────────
    tag_pattern: dict[str, Any] = field(default_factory=dict)
    user_habits: dict[str, Any] = field(default_factory=dict)

    # ── Sessions + adherence style ─────────────────────────────────────────
    sessions_14d: dict[str, Any] = field(default_factory=dict)
    plan_deviations_30d: dict[str, Any] = field(default_factory=dict)
    adherence_30d: dict[str, Any] = field(default_factory=dict)

    # ── Existing UUP traits (personality lens + continuity) ───────────────
    uup: dict[str, Any] = field(default_factory=dict)

    # ── Future placeholders (not wired yet) ───────────────────────────────
    future_signals: dict[str, Any] = field(default_factory=dict)


async def build_coach_input_packet(
    session: AsyncSession,
    user_id: uuid_mod.UUID,
) -> CoachInputPacket:
    """
    Assemble a complete `CoachInputPacket` from DB rows.
    """

    tz = product_calendar_timezone()
    now_utc = datetime.now(UTC)
    today = local_today(now_utc)
    today_str = today.isoformat()
    # Use the local date encoded as UTC-midnight (existing DB contract).
    today_midnight_utc = datetime(today.year, today.month, today.day, tzinfo=UTC)

    # ── Personal model + UUP traits ─────────────────────────────────────────
    pm_row, uup_row, psych_row, habits_row, tag_model_row = await asyncio.gather(
        session.scalar(select(db.PersonalModel).where(db.PersonalModel.user_id == user_id)),
        session.scalar(select(db.UserUnifiedProfile).where(db.UserUnifiedProfile.user_id == user_id)),
        session.scalar(select(db.UserPsychProfile).where(db.UserPsychProfile.user_id == user_id)),
        session.scalar(select(db.UserHabits).where(db.UserHabits.user_id == user_id)),
        session.scalar(select(db.TagPatternModel).where(db.TagPatternModel.user_id == user_id)),
    )

    personal_model = {
        "rmssd_floor": getattr(pm_row, "rmssd_floor", None),
        "rmssd_ceiling": getattr(pm_row, "rmssd_ceiling", None),
        "rmssd_morning_avg": getattr(pm_row, "rmssd_morning_avg", None),
        "rmssd_resting_hr_bpm": getattr(pm_row, "rmssd_resting_hr_bpm", None),
        "recovery_arc": {
            "mean_hours": getattr(pm_row, "recovery_arc_mean_hours", None),
            "fast_hours": getattr(pm_row, "recovery_arc_fast_hours", None),
            "slow_hours": getattr(pm_row, "recovery_arc_slow_hours", None),
        }
        if pm_row is not None
        else {},
        "coherence_trainability": getattr(pm_row, "coherence_trainability", None),
        "stress_peak_day": getattr(pm_row, "stress_peak_day", None),
        "stress_peak_hour": getattr(pm_row, "stress_peak_hour", None),
        "sleep_recovery_efficiency": getattr(pm_row, "sleep_recovery_efficiency", None),
        "overnight_rmssd_delta_avg": getattr(pm_row, "overnight_rmssd_delta_avg", None),
        "prf_bpm": getattr(pm_row, "prf_bpm", None),
        "lf_hf_resting": getattr(pm_row, "lf_hf_resting", None),
        "stress_capacity_floor_rmssd": getattr(pm_row, "stress_capacity_floor_rmssd", None),
    }

    uup = {
        "engagement_tier": getattr(uup_row, "engagement_tier", None) if uup_row is not None else None,
        "preferred_tone": getattr(uup_row, "preferred_tone", None) if uup_row is not None else None,
        "band_days_worn_last7": getattr(uup_row, "band_days_worn_last7", None) if uup_row is not None else None,
        "band_days_worn_last30": getattr(uup_row, "band_days_worn_last30", None) if uup_row is not None else None,
        "sessions_last7": getattr(uup_row, "sessions_last7", None) if uup_row is not None else None,
        "coach_watch_notes": getattr(uup_row, "coach_watch_notes", None) if uup_row is not None else None,
        # Existing narrative for continuity/delta (optional)
        "previous_coach_narrative": getattr(uup_row, "coach_narrative", None) if uup_row is not None else None,
    }

    # ── Daily trajectory (last 14 days) ────────────────────────────────────
    start_14 = today_midnight_utc - timedelta(days=13)
    daily_rows_res = await session.execute(
        select(db.DailyStressSummary)
        .where(
            and_(
                db.DailyStressSummary.user_id == user_id,
                db.DailyStressSummary.summary_date >= start_14,
                db.DailyStressSummary.summary_date <= today_midnight_utc,
            )
        )
        .order_by(db.DailyStressSummary.summary_date.asc())
    )
    daily_rows = list(daily_rows_res.scalars().all())

    daily_trajectory: list[dict[str, Any]] = []
    for r in daily_rows:
        sleep_recovery_score = getattr(r, "sleep_recovery_score", None)
        if sleep_recovery_score is None:
            sleep_recovery_score = _compute_sleep_recovery_score_from_raw(
                getattr(r, "raw_recovery_area_sleep", None),
                getattr(r, "ns_capacity_recovery", None),
            )

        raw_stress = getattr(r, "stress_load_score", None)
        stress_load_0_10: float | None = None
        if raw_stress is not None:
            try:
                stress_load_0_10 = round(float(raw_stress) / 10.0, 1)
            except (TypeError, ValueError):
                pass

        daily_trajectory.append(
            {
                "date": r.summary_date.date().isoformat() if getattr(r, "summary_date", None) else None,
                # Composite readiness 0–100 (from prior day metrics); waking/sleep 0–100.
                "readiness_score": getattr(r, "readiness_score", None),
                "waking_recovery_score": getattr(r, "waking_recovery_score", None),
                "sleep_recovery_score": sleep_recovery_score,
                # stress_load is expressed on the same 0–10 scale the app shows the user.
                "stress_load_score": stress_load_0_10,
                "day_type": getattr(r, "day_type", None),
            }
        )

    # ── Morning reads (last 7) ────────────────────────────────────────────
    pm = pm_row
    floor = getattr(pm, "rmssd_floor", None) if pm is not None else None
    avg = getattr(pm, "rmssd_morning_avg", None) if pm is not None else None

    start_7_morning = today_midnight_utc - timedelta(days=6)
    morning_res = await session.execute(
        select(db.MorningRead)
        .where(
            and_(
                db.MorningRead.user_id == user_id,
                db.MorningRead.read_date >= start_7_morning,
                db.MorningRead.read_date <= today_midnight_utc,
            )
        )
        .order_by(db.MorningRead.read_date.asc())
    )
    morning_rows = list(morning_res.scalars().all())

    morning_reads: list[dict[str, Any]] = []
    for mr in morning_rows:
        rmssd_ms = getattr(mr, "rmssd_ms", None)
        pct_floor: Optional[str] = None
        pct_avg: Optional[str] = None
        vs_personal_avg_pct = getattr(mr, "vs_personal_avg_pct", None)

        if rmssd_ms is not None and floor is not None and floor > 0:
            delta = (rmssd_ms - floor) / floor
            pct_floor = _pct_str(delta, reference="your floor")
        if rmssd_ms is not None and avg is not None and avg > 0:
            delta = (rmssd_ms - avg) / avg
            pct_avg = _pct_str(delta, reference="your average")

        morning_reads.append(
            {
                "read_date": mr.read_date.date().isoformat() if getattr(mr, "read_date", None) else None,
                "rmssd_vs_floor": pct_floor,
                "rmssd_vs_avg": pct_avg,
                "hr_bpm": getattr(mr, "hr_bpm", None),
                "lf_hf": getattr(mr, "lf_hf", None),
                "vs_personal_avg_pct": vs_personal_avg_pct,
                "confidence": getattr(mr, "confidence", None),
                "day_type": getattr(mr, "day_type", None),
            }
        )

    # ── Stress windows (48h) + 30d tag aggregates ─────────────────────────
    cutoff_48 = now_utc - timedelta(hours=48)
    stress_res = await session.execute(
        select(db.StressWindow)
        .where(
            and_(
                db.StressWindow.user_id == user_id,
                db.StressWindow.started_at >= cutoff_48,
            )
        )
        .order_by(db.StressWindow.started_at.asc())
    )
    stress_rows = list(stress_res.scalars().all())

    # 30d top stressor tags (from confirmed tags)
    cutoff_30 = now_utc - timedelta(days=30)
    tag_counts: dict[str, int] = {}
    stress_30_res = await session.execute(
        select(db.StressWindow)
        .where(
            and_(
                db.StressWindow.user_id == user_id,
                db.StressWindow.started_at >= cutoff_30,
                db.StressWindow.tag.isnot(None),
            )
        )
    )
    for sr in list(stress_30_res.scalars().all()):
        tag = sr.tag
        if not tag:
            continue
        tag_counts[str(tag)] = tag_counts.get(str(tag), 0) + 1
    top_trigger_tags = sorted(tag_counts.items(), key=lambda kv: -kv[1])[:3]

    stress_windows_48h = {
        "events": [
            {
                "started_at": sw.started_at.isoformat() if sw.started_at else None,
                "ended_at": sw.ended_at.isoformat() if sw.ended_at else None,
                "duration_minutes": getattr(sw, "duration_minutes", None),
                "tag": getattr(sw, "tag", None) or getattr(sw, "tag_candidate", None),
                "suppression_pct": (
                    round(float(sw.suppression_pct) * 100.0, 1)
                    if getattr(sw, "suppression_pct", None) is not None
                    else None
                ),
            }
            for sw in stress_rows
        ],
        "count": len(stress_rows),
        "top_trigger_tags_30d": [
            {"tag": t, "count": c} for t, c in top_trigger_tags
        ],
    }

    # ── Recovery windows (48h) + 30d tag aggregates ──────────────────────
    rec_res = await session.execute(
        select(db.RecoveryWindow)
        .where(
            and_(
                db.RecoveryWindow.user_id == user_id,
                db.RecoveryWindow.started_at >= cutoff_48,
            )
        )
        .order_by(db.RecoveryWindow.started_at.asc())
    )
    rec_rows = list(rec_res.scalars().all())

    rec_tag_counts: dict[str, int] = {}
    rec_30_res = await session.execute(
        select(db.RecoveryWindow)
        .where(
            and_(
                db.RecoveryWindow.user_id == user_id,
                db.RecoveryWindow.started_at >= cutoff_30,
                db.RecoveryWindow.tag.isnot(None),
            )
        )
    )
    for rr in list(rec_30_res.scalars().all()):
        tag = rr.tag
        if not tag:
            continue
        rec_tag_counts[str(tag)] = rec_tag_counts.get(str(tag), 0) + 1
    top_calm_tags = sorted(rec_tag_counts.items(), key=lambda kv: -kv[1])[:3]

    recovery_windows_48h = {
        "events": [
            {
                "started_at": rw.started_at.isoformat() if rw.started_at else None,
                "ended_at": rw.ended_at.isoformat() if rw.ended_at else None,
                "duration_minutes": getattr(rw, "duration_minutes", None),
                "context": getattr(rw, "context", None),
                "tag": getattr(rw, "tag", None),
                "recovery_score_lift": None,  # placeholder until better evidence wiring
            }
            for rw in rec_rows
        ],
        "count": len(rec_rows),
        "top_calm_activities_30d": [
            {"tag": t, "count": c} for t, c in top_calm_tags
        ],
    }

    # ── Background bins (24h, 4h buckets) ─────────────────────────────────
    ceiling = getattr(pm, "rmssd_ceiling", None) if pm is not None else None
    bg_cutoff = now_utc - timedelta(hours=24)
    background_bins: list[dict[str, Any]] = []
    if ceiling and ceiling > 0:
        bg_res = await session.execute(
            select(db.BackgroundWindow)
            .where(
                and_(
                    db.BackgroundWindow.user_id == user_id,
                    db.BackgroundWindow.window_start >= bg_cutoff,
                    db.BackgroundWindow.is_valid.is_(True),
                    db.BackgroundWindow.context == "background",
                )
            )
            .order_by(db.BackgroundWindow.window_start.asc())
        )
        bg_rows = list(bg_res.scalars().all())

        slot_values: dict[int, list[float]] = {}
        for bw in bg_rows:
            if bw.rmssd_ms is None:
                continue
            start = bw.window_start
            slot = (start.hour // 4) * 4
            slot_values.setdefault(slot, []).append(float(bw.rmssd_ms))

        for slot_start in sorted(slot_values.keys()):
            values = slot_values[slot_start]
            if not values:
                continue
            avg_ms = sum(values) / len(values)
            pct = round((avg_ms / float(ceiling)) * 100.0, 1)
            slot_end = (slot_start + 4) % 24
            background_bins.append(
                {
                    "time_label": f"{slot_start:02d}:00–{slot_end:02d}:00",
                    "rmssd_pct_ceiling": pct,
                    "window_count": len(values),
                }
            )

    # ── Sessions (14d summary) ────────────────────────────────────────────
    cutoff_14 = now_utc - timedelta(days=14)
    sess_res = await session.execute(
        select(db.Session)
        .where(
            and_(
                db.Session.user_id == user_id,
                db.Session.started_at >= cutoff_14,
                db.Session.ended_at.isnot(None),
            )
        )
        .order_by(db.Session.ended_at.desc())
    )
    sess_rows = list(sess_res.scalars().all())
    last_session_ago_days: Optional[int] = None
    completed_count = len(sess_rows)
    coherence_vals: list[float] = []

    for s in sess_rows:
        if s.coherence_avg is not None:
            coherence_vals.append(float(s.coherence_avg))

    if sess_rows:
        last_ended = sess_rows[0].ended_at
        if last_ended:
            # Compare local calendar days for user-facing language.
            last_local = last_ended.astimezone(tz).date()
            last_session_ago_days = (today - last_local).days

    sessions_this_week = 0
    week_cutoff = today_midnight_utc - timedelta(days=7)
    for s in sess_rows:
        if s.ended_at and s.ended_at.astimezone(tz) >= week_cutoff:
            sessions_this_week += 1

    sessions_14d = {
        "completed_count": completed_count,
        "sessions_this_week": sessions_this_week,
        "last_session_ago_days": last_session_ago_days,
        "coherence_avg_per_session": (
            round(sum(coherence_vals) / len(coherence_vals), 3) if coherence_vals else None
        ),
        # Per-session metrics needed for post-session nudge trigger (T5)
        "last_session": (
            {
                "session_score": sess_rows[0].session_score,
                "ended_at": sess_rows[0].ended_at.isoformat() if sess_rows[0].ended_at else None,
                "pi_pre": sess_rows[0].pi_pre,
            }
            if sess_rows
            else {}
        ),
    }

    # ── Habit events (72h) ────────────────────────────────────────────────
    cutoff_habit = now_utc - timedelta(hours=72)
    habit_res = await session.execute(
        select(db.HabitEvent)
        .where(
            and_(
                db.HabitEvent.user_id == user_id,
                db.HabitEvent.ts >= cutoff_habit,
            )
        )
        .order_by(db.HabitEvent.ts.desc())
        .limit(50)
    )
    habit_rows = list(habit_res.scalars().all())
    habit_events_72h: list[dict[str, Any]] = []
    for he in habit_rows:
        ts = he.ts
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        hours_ago = (now_utc - ts).total_seconds() / 3600.0
        habit_events_72h.append(
            {
                "event_type": he.event_type,
                "severity": he.severity,
                "hours_ago": round(hours_ago, 2),
                "source": he.source,
                "rmssd_delta_next_morning": getattr(he, "rmssd_delta_next_morning", None),
            }
        )

    # ── Check-ins (7d) ───────────────────────────────────────────────────
    cutoff_checkin = now_utc - timedelta(days=7)
    checkin_res = await session.execute(
        select(db.CheckIn)
        .where(and_(db.CheckIn.user_id == user_id, db.CheckIn.created_at >= cutoff_checkin))
        .order_by(db.CheckIn.created_at.desc())
        .limit(20)
    )
    checkin_rows = list(checkin_res.scalars().all())
    check_ins_7d: list[dict[str, Any]] = []
    for ci in checkin_rows:
        ts = ci.created_at or now_utc
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        age_hours = (now_utc - ts).total_seconds() / 3600.0
        check_ins_7d.append(
            {
                "reactivity": ci.reactivity,
                "focus": ci.focus,
                "recovery": ci.recovery,
                "age_hours": round(age_hours, 1),
                "created_at": ts.isoformat(),
            }
        )

    # ── Anxiety events (14d) ──────────────────────────────────────────────
    cutoff_anx = now_utc - timedelta(days=14)
    anx_res = await session.execute(
        select(db.AnxietyEvent)
        .where(and_(db.AnxietyEvent.user_id == user_id, db.AnxietyEvent.ts >= cutoff_anx))
        .order_by(db.AnxietyEvent.ts.desc())
        .limit(30)
    )
    anx_rows = list(anx_res.scalars().all())
    anxiety_events_14d: list[dict[str, Any]] = []
    for ax in anx_rows:
        ts = ax.ts
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        anxiety_events_14d.append(
            {
                "trigger_type": ax.trigger_type,
                "severity": ax.severity,
                "resolved": getattr(ax, "resolved", None),
                "stress_score_at_event": getattr(ax, "stress_score_at_event", None),
                "recovery_score_drop": getattr(ax, "recovery_score_drop", None),
                "reported_via": getattr(ax, "reported_via", None),
                "ts": ts.isoformat(),
            }
        )

    # ── Conversation memory (3d) ──────────────────────────────────────────
    cutoff_conv = now_utc - timedelta(days=3)
    conv_res = await session.execute(
        select(db.ConversationEvent)
        .where(and_(db.ConversationEvent.user_id == user_id, db.ConversationEvent.ts >= cutoff_conv))
        .order_by(db.ConversationEvent.ts.desc())
        .limit(10)
    )
    conv_rows = list(conv_res.scalars().all())
    conversation_events_3d: list[dict[str, Any]] = []
    for ev in conv_rows:
        ts = ev.ts
        if ts and ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        conversation_events_3d.append(
            {
                "role": ev.role,
                "content": _sanitize_text(ev.content, max_len=500),
                "ts": ts.isoformat() if ts else None,
                "plan_adjusted": getattr(ev, "plan_adjusted", None),
            }
        )

    # ── User facts (confidence >= 0.7) ────────────────────────────────────
    facts_res = await session.execute(
        select(db.UserFact)
        .where(and_(db.UserFact.user_id == user_id, db.UserFact.confidence >= 0.7))
        .order_by(db.UserFact.confidence.desc())
        .limit(12)
    )
    user_facts = [
        _sanitize_text(f.fact_text, max_len=140)
        for f in list(facts_res.scalars().all())
        if getattr(f, "fact_text", None)
    ]

    # ── Tag pattern + user habits ──────────────────────────────────────────
    tag_pattern = {
        "sport_stressor_slugs": getattr(tag_model_row, "sport_stressor_slugs", None) or [],
        "model_json": getattr(tag_model_row, "model_json", None) or {},
    }
    user_habits = {
        "movement_enjoyed": getattr(habits_row, "movement_enjoyed", None) or [],
        "decompress_via": getattr(habits_row, "decompress_via", None) or [],
        "stress_drivers": getattr(habits_row, "stress_drivers", None) or [],
        "alcohol": getattr(habits_row, "alcohol", None),
        "caffeine": getattr(habits_row, "caffeine", None),
        "sleep_schedule": getattr(habits_row, "sleep_schedule", None),
    }

    # ── Plan adherence / deviations (30d) ─────────────────────────────────
    plan_start_30 = today_midnight_utc - timedelta(days=29)
    adherence_res = await session.execute(
        select(db.DailyPlan)
        .where(
            and_(
                db.DailyPlan.user_id == user_id,
                db.DailyPlan.plan_date >= plan_start_30,
                db.DailyPlan.plan_date <= today_midnight_utc + timedelta(days=1),
            )
        )
    )
    daily_plan_rows = list(adherence_res.scalars().all())
    adherence_vals = [p.adherence_pct for p in daily_plan_rows if p.adherence_pct is not None]
    adherence_30d = {
        "adherence_avg": round(sum(adherence_vals) / len(adherence_vals), 1) if adherence_vals else None,
        "days_with_data": len(adherence_vals),
    }

    dev_res = await session.execute(
        select(db.PlanDeviation)
        .where(and_(db.PlanDeviation.user_id == user_id, db.PlanDeviation.ts >= (now_utc - timedelta(days=30))))
    )
    dev_rows = list(dev_res.scalars().all())
    reason_counts: dict[str, int] = {}
    for dv in dev_rows:
        reason = dv.reason_category or "unknown"
        reason_counts[str(reason)] = reason_counts.get(str(reason), 0) + 1
    top_deviation_reasons = sorted(reason_counts.items(), key=lambda kv: -kv[1])[:5]

    plan_deviations_30d = {
        "top_reasons": [{"reason": r, "count": c} for r, c in top_deviation_reasons],
        "total_deviations": len(dev_rows),
    }

    # ── Future signals (best-effort) ──────────────────────────────────────
    future_signals: dict[str, Any] = {
        "hr_bpm_resting": getattr(pm, "rmssd_resting_hr_bpm", None) if pm is not None else None,
        "spo2_avg": None,
        "pi_baseline": None,
        "lf_hf_daily": getattr(pm, "lf_hf_resting", None) if pm is not None else None,
        "sdnn_avg": None,
        "hf_power_avg": None,
    }

    # Perfusion index baseline if we have enough session pi_pre values.
    pi_pre_vals = [float(s.pi_pre) for s in sess_rows if getattr(s, "pi_pre", None) is not None]
    if pi_pre_vals:
        pi_pre_vals.sort()
        mid = len(pi_pre_vals) // 2
        if len(pi_pre_vals) % 2 == 1:
            future_signals["pi_baseline"] = round(pi_pre_vals[mid], 3)
        else:
            future_signals["pi_baseline"] = round((pi_pre_vals[mid - 1] + pi_pre_vals[mid]) / 2.0, 3)

    # ── Done ───────────────────────────────────────────────────────────────
    return CoachInputPacket(
        user_id=str(user_id),
        today_local_date=today_str,
        personal_model=personal_model,
        daily_trajectory=daily_trajectory,
        morning_reads=morning_reads,
        stress_windows_48h=stress_windows_48h,
        recovery_windows_48h=recovery_windows_48h,
        background_bins_24h=background_bins,
        habit_events_72h=habit_events_72h,
        check_ins_7d=check_ins_7d,
        anxiety_events_14d=anxiety_events_14d,
        conversation_events_3d=conversation_events_3d,
        user_facts=user_facts,
        tag_pattern=tag_pattern,
        user_habits=user_habits,
        sessions_14d=sessions_14d,
        plan_deviations_30d=plan_deviations_30d,
        adherence_30d=adherence_30d,
        uup=uup,
        future_signals=future_signals,
    )

