"""
jobs/nightly_rebuild.py

Nightly background job runner.

Runs these tasks sequentially for all active users:
  1. Unified Profile rebuild (Layer 1 narrative + Layer 2 plan + Layer 3 guardrails)
  2. Psych profile streak increment (yesterday's adherence → streak_current)
  3. Auto-tag pass stub (placeholder — pattern model not yet fully wired)

Intended to run once per morning at 6:30 AM IST (01:00 UTC) via APScheduler,
or a cloud scheduler (AWS EventBridge, GCP Cloud Scheduler, etc.).
This timing ensures a full night of sleep data has been collected before
the narrative is generated, giving the readiness verdict full context.

Usage
-----
Standalone execution (for cron / docker entrypoint):
    python -m jobs.nightly_rebuild

FastAPI APScheduler integration (add to api/main.py lifespan):
    from jobs.nightly_rebuild import run_nightly_rebuild
    scheduler.add_job(run_nightly_rebuild, trigger="cron", hour=1, minute=0)  # 6:30 AM IST = 01:00 UTC

Environment variables used:
    OPENAI_API_KEY     — LLM key (optional; fallback runs if absent)
    LLM_ENABLED        — "true"|"false"
    DATABASE_URL       — postgres async URL

Design
------
Active users = users with at least one Session or MorningRead in the last 30 days.
Inactive users are skipped to avoid redundant LLM calls.
Each user rebuild is independent — one failure does not block others.
All errors are logged with user context; no exception propagates to the scheduler.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

log = logging.getLogger(__name__)


def _extract_watch_today_bullets(narrative: Optional[str]) -> list[str]:
    """
    Extract WATCH TODAY bullets from the narrative text.
    """
    if not narrative:
        return []

    m = re.search(
        r"WATCH TODAY\s*\n(.*?)(?=\n[A-Z][A-Z ]+\n|\Z)",
        narrative,
        flags=re.DOTALL,
    )
    if not m:
        return []

    block = m.group(1)
    bullets: list[str] = []
    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith(("•", "-", "*")):
            cleaned = stripped.lstrip("•-*").strip()
            if cleaned:
                bullets.append(cleaned)
    return bullets[:5]


def _fallback_layer2_narrative(packet: Any) -> str:
    """
    Deterministic Layer 2 narrative when LLM is disabled.
    """
    today_row = None
    yesterday_row = None
    if getattr(packet, "daily_trajectory", None):
        for r in packet.daily_trajectory:
            if r.get("date") == packet.today_local_date:
                today_row = r
        if today_row is not None:
            idx = packet.daily_trajectory.index(today_row)
            if idx - 1 >= 0:
                yesterday_row = packet.daily_trajectory[idx - 1]
        elif len(packet.daily_trajectory) >= 2:
            today_row = packet.daily_trajectory[-1]
            yesterday_row = packet.daily_trajectory[-2]

    readiness = (today_row or {}).get("readiness_score")
    waking = (today_row or {}).get("waking_recovery_score")
    sleep = (today_row or {}).get("sleep_recovery_score")
    stress = (today_row or {}).get("stress_load_score")
    day_type = (today_row or {}).get("day_type")

    # Keep this simple and grounded: we only cite available numbers.
    readiness_s = f"{readiness:.1f}" if readiness is not None else "unknown"
    waking_s = f"{waking:.1f}" if waking is not None else "unknown"
    sleep_s = f"{sleep:.1f}" if sleep is not None else "unknown"
    stress_s = f"{stress:.1f}" if stress is not None else "unknown"

    # Decide push vs protect heuristically from readiness.
    try:
        readiness_v = float(readiness) if readiness is not None else 50.0
    except Exception:
        readiness_v = 50.0

    if readiness_v >= 70:
        verdict = "push"
        watch = [
            "Start with a light warm-up, then do your main block.",
            "If stress spikes during the session, switch to breathing_only immediately.",
            "Keep the rest of the day active but not aggressive.",
        ]
    elif readiness_v >= 45:
        verdict = "maintain"
        watch = [
            "Keep intensity moderate and pace your breathing between sets.",
            "Choose recovery-friendly movement if stress rises again.",
            "Don’t stack late nights onto a busy training day.",
        ]
    else:
        verdict = "protect"
        watch = [
            "Protect recovery first: short breathing + easy movement only.",
            "Avoid hard effort if you feel reactivity building.",
            "Plan an earlier wind-down to help your sleep rebound.",
        ]

    checkins = getattr(packet, "check_ins_7d", None) or []
    last_checkin = checkins[0] if checkins else None
    if last_checkin:
        reactivity = last_checkin.get("reactivity")
        focus = last_checkin.get("focus")
        recovery = last_checkin.get("recovery")
    else:
        reactivity = focus = recovery = None

    reactivity_s = str(reactivity) if reactivity is not None else "unknown"
    focus_s = str(focus) if focus is not None else "unknown"
    recovery_s = str(recovery) if recovery is not None else "unknown"

    return f"""\
PHYSIO PROFILE
• Today readiness is {readiness_s}/100, with waking recovery {waking_s}/100 and sleep recovery {sleep_s}/100.
• Stress load is {stress_s}/100, so your system likely has {verdict} capacity for the day.

YESTERDAY RECAP
• Yesterday day type was {((yesterday_row or {}).get("day_type") or "unknown")}. Your readiness trend is now {'improving' if verdict=='push' else 'needs care'}.

SUBJECTIVE ALIGNMENT
• Your latest check-in scores: reactivity {reactivity_s}/5, focus {focus_s}/5, recovery {recovery_s}/5.
• If reactivity is high while recovery is low, choose the protective version of today.

BEHAVIORAL SIGNALS
• Recent habit events and sessions should guide your next step, but no specific event detail is available in fallback mode.

LONGITUDINAL SIGNALS
• Over the last two weeks, your plan consistency and recovery signals suggest a {verdict} approach today.

WHAT THEY LIKE / WHAT HELPS
• Use what typically helps you recover; if sleep recovery is low, prioritize wind-down routines.

READINESS VERDICT
• Verdict: {verdict.upper()} today (day type: {day_type or 'unknown'}).

WATCH TODAY
• {watch[0]}
• {watch[1]}
• {watch[2]}
""".strip()


# ── Active user detection ─────────────────────────────────────────────────────

async def _get_active_user_ids(session) -> list:
    """Return UUIDs of users active in the last 30 days."""
    from sqlalchemy import select, func, union, and_
    import api.db.schema as db

    cutoff = datetime.now(UTC) - timedelta(days=30)

    session_users = select(db.Session.user_id).where(
        db.Session.started_at >= cutoff
    )
    read_users = select(db.MorningRead.user_id).where(
        db.MorningRead.read_date >= cutoff
    )
    # Also include users who have background windows (the primary data source
    # for Verity — users may never have a Session or MorningRead row yet)
    background_users = select(db.BackgroundWindow.user_id).where(
        db.BackgroundWindow.window_start >= cutoff
    )
    all_active = union(session_users, read_users, background_users).subquery()

    result = await session.execute(
        select(all_active.c.user_id).distinct()
    )
    return [row[0] for row in result.all()]


# ── Streak increment ───────────────────────────────────────────────────────────

async def _increment_streak(session, user_id) -> None:
    """
    Check yesterday's DailyPlan adherence. If ≥1 must_do completed:
      streak_current += 1; streak_best = max(streak_best, streak_current)
    If no plan or 0 completed:
      streak_current = 0
    Updates UserPsychProfile.
    """
    from sqlalchemy import select, and_, func
    import api.db.schema as db
    from tracking.cycle_boundaries import recap_yesterday_local_date

    # Use product local date so "yesterday" matches the plan_date calendar day
    yesterday = recap_yesterday_local_date()
    yesterday_start = datetime.combine(yesterday, datetime.min.time()).replace(tzinfo=UTC)
    yesterday_end   = datetime.combine(yesterday, datetime.max.time()).replace(tzinfo=UTC)

    # Get yesterday's plan
    plan_result = await session.execute(
        select(db.DailyPlan).where(
            and_(
                db.DailyPlan.user_id == user_id,
                db.DailyPlan.plan_date >= yesterday_start,
                db.DailyPlan.plan_date <= yesterday_end,
            )
        )
    )
    plan = plan_result.scalar_one_or_none()

    # Get psych profile
    psych_result = await session.execute(
        select(db.UserPsychProfile).where(db.UserPsychProfile.user_id == user_id)
    )
    psych = psych_result.scalar_one_or_none()
    if psych is None:
        return

    if plan is None or plan.adherence_pct is None or plan.adherence_pct < 0.1:
        # No plan or no completion — reset streak
        if psych.streak_current and psych.streak_current > 0:
            log.debug("streak_reset user=%s (no plan or 0 adherence)", user_id)
            psych.streak_current = 0
    else:
        # Has some adherence — increment streak
        psych.streak_current = (psych.streak_current or 0) + 1
        if psych.streak_current > (psych.streak_best or 0):
            psych.streak_best = psych.streak_current
        log.debug("streak_increment user=%s streak=%d", user_id, psych.streak_current)

    await session.commit()


# ── Auto-tag pass stub ────────────────────────────────────────────────────────

async def _auto_tag_pass(session, user_id) -> int:
    """
    Run nightly auto-tag pass via TaggingService.
    Returns number of newly tagged windows.
    """
    from api.services.tagging_service import TaggingService

    svc = TaggingService(db=session)
    result = await svc.run_auto_tag_pass(str(user_id))
    return int(result.tagged_count or 0)


# ── Capacity growth detection ─────────────────────────────────────────────────

async def _check_capacity_growth(session, user_id) -> dict:
    """
    Detect genuine NS capacity growth and trigger re-calibration when confirmed.

    Design (CONTEXT.md Step 6 / config/model.py):
    - Only runs post-calibration-lock (calibration_locked_at IS NOT NULL).
    - Each day yesterday's peak valid RMSSD > locked_ceiling * growth_threshold
      increments capacity_growth_streak.
    - Any day below threshold (band worn, data present) resets streak to 0.
    - No data (band not worn) is neutral — streak does not advance or reset.
    - When streak reaches CAPACITY_GROWTH_CONFIRM_DAYS:
        1. Snapshot current PersonalModel state.
        2. Update rmssd_ceiling to the new max RMSSD over the confirm window.
        3. Update rmssd_morning_avg to recent morning read average (if available).
        4. Reset calibration_locked_at = now() (re-lock at new ceiling).
        5. Increment capacity_version.
        6. Reset capacity_growth_streak = 0.

    Returns dict with keys: ran, triggered, new_ceiling, streak_after.
    """
    from sqlalchemy import select, func, and_
    import api.db.schema as db
    from config import CONFIG

    result: dict = {
        "ran": False, "triggered": False,
        "new_ceiling": None, "streak_after": 0,
    }

    # Fetch personal model
    pm_res = await session.execute(
        select(db.PersonalModel).where(db.PersonalModel.user_id == user_id)
    )
    personal = pm_res.scalar_one_or_none()

    # Only run post-lock, and only if floor+ceiling are established
    if (personal is None
            or personal.calibration_locked_at is None
            or personal.rmssd_ceiling is None
            or personal.rmssd_floor is None):
        return result

    result["ran"] = True
    locked_ceiling   = personal.rmssd_ceiling
    growth_threshold = 1.0 + CONFIG.model.CAPACITY_GROWTH_THRESHOLD_PCT / 100.0
    confirm_days     = CONFIG.model.CAPACITY_GROWTH_CONFIRM_DAYS

    # Query yesterday's peak valid RMSSD
    yesterday       = (datetime.now(UTC) - timedelta(days=1)).date()
    yesterday_start = datetime.combine(yesterday, datetime.min.time()).replace(tzinfo=UTC)
    yesterday_end   = datetime.combine(yesterday, datetime.max.time()).replace(tzinfo=UTC)

    peak_res = await session.execute(
        select(func.max(db.BackgroundWindow.rmssd_ms)).where(
            and_(
                db.BackgroundWindow.user_id  == user_id,
                db.BackgroundWindow.window_start >= yesterday_start,
                db.BackgroundWindow.window_start <= yesterday_end,
                db.BackgroundWindow.is_valid     == True,
                db.BackgroundWindow.rmssd_ms.isnot(None),
            )
        )
    )
    yesterday_peak = peak_res.scalar_one_or_none()

    # No valid data for yesterday → band not worn; don't advance or reset streak
    if yesterday_peak is None:
        result["streak_after"] = personal.capacity_growth_streak or 0
        return result

    if yesterday_peak > locked_ceiling * growth_threshold:
        # Growth signal — advance streak
        new_streak = (personal.capacity_growth_streak or 0) + 1
        personal.capacity_growth_streak = new_streak
        result["streak_after"] = new_streak
        log.debug(
            "capacity_growth_streak user=%s streak=%d peak_rmssd=%.1f ceiling=%.1f",
            user_id, new_streak, yesterday_peak, locked_ceiling,
        )

        if new_streak >= confirm_days:
            # ── Trigger re-lock ───────────────────────────────────────────────
            # New ceiling = max valid RMSSD across the entire confirm window
            window_start = datetime.now(UTC) - timedelta(days=confirm_days + 1)
            new_peak_res = await session.execute(
                select(func.max(db.BackgroundWindow.rmssd_ms)).where(
                    and_(
                        db.BackgroundWindow.user_id     == user_id,
                        db.BackgroundWindow.window_start >= window_start,
                        db.BackgroundWindow.is_valid     == True,
                        db.BackgroundWindow.rmssd_ms.isnot(None),
                    )
                )
            )
            new_ceiling = new_peak_res.scalar_one_or_none() or yesterday_peak

            # Snapshot state before mutation
            snapshot = db.ModelSnapshot(
                user_id=user_id,
                model_version=personal.capacity_version or 0,
                snapshot_json={
                    "rmssd_floor":       personal.rmssd_floor,
                    "rmssd_ceiling":     locked_ceiling,
                    "rmssd_morning_avg": personal.rmssd_morning_avg,
                    "capacity_version":  personal.capacity_version,
                    "trigger":           "capacity_growth",
                    "confirmed_streak":  new_streak,
                },
            )
            session.add(snapshot)

            # Apply growth: update ceiling, morning_avg, re-lock
            personal.rmssd_ceiling         = new_ceiling
            # morning_avg grows proportionally with the new ceiling
            personal.rmssd_morning_avg = round(
                personal.rmssd_floor + 0.37 * (new_ceiling - personal.rmssd_floor), 1
            )
            personal.calibration_locked_at  = datetime.now(UTC)
            personal.capacity_version       = (personal.capacity_version or 0) + 1
            personal.capacity_growth_streak = 0

            result["triggered"]   = True
            result["new_ceiling"] = new_ceiling
            result["streak_after"] = 0
            log.info(
                "capacity_growth TRIGGERED user=%s old_ceiling=%.1f new_ceiling=%.1f "
                "new_capacity_version=%d",
                user_id, locked_ceiling, new_ceiling, personal.capacity_version,
            )
    else:
        # Below threshold — reset streak
        if (personal.capacity_growth_streak or 0) > 0:
            log.debug(
                "capacity_growth_streak RESET user=%s (peak %.1f ≤ threshold %.1f)",
                user_id, yesterday_peak, locked_ceiling * growth_threshold,
            )
        personal.capacity_growth_streak = 0
        result["streak_after"] = 0

    await session.flush()
    return result


# ── Assessor helper ───────────────────────────────────────────────────────────

async def _run_assessor(session, user_id) -> "Optional[Any]":
    """
    Fetch the minimal data needed by assessor.assess_user() and call it.

    SessionRecord  — last 10 Sessions (context="session"); completed = ended_at IS NOT NULL.
    RecoveryRecord — last 28 DailyStressSummary rows; recovery = waking_recovery_score.
    DeviationRecord — last 30 days of PlanDeviation rows.
    adherence_by_category — 7-day adherence per DailyPlan item category.

    assess_user() is synchronous so we call it directly (no asyncio.to_thread
    needed on CPython for pure-Python operations).
    """
    from sqlalchemy import select, and_
    import api.db.schema as db
    from coach.assessor import (
        assess_user, SessionRecord, RecoveryRecord, DeviationRecord,
        UserAssessment,
    )
    from datetime import date as date_type

    cutoff_30d = datetime.now(UTC) - timedelta(days=30)
    cutoff_28d = datetime.now(UTC) - timedelta(days=28)

    # ── Sessions ──────────────────────────────────────────────────────────────
    sess_res = await session.execute(
        select(db.Session)
        .where(
            and_(
                db.Session.user_id  == user_id,
                db.Session.context  == "session",
            )
        )
        .order_by(db.Session.started_at.desc())
        .limit(10)
    )
    session_rows = sess_res.scalars().all()
    session_records = [
        SessionRecord(
            session_id=str(row.id),
            session_score=(row.session_score / 100.0) if row.session_score is not None else None,
            was_prescribed=True,   # all ZenFlow sessions are prescribed
            completed=row.ended_at is not None,
        )
        for row in reversed(session_rows)   # oldest first
    ]

    # ── Readiness (28-day DailyStressSummary) ────────────────────────────────
    rdy_res = await session.execute(
        select(db.DailyStressSummary)
        .where(
            and_(
                db.DailyStressSummary.user_id       == user_id,
                db.DailyStressSummary.summary_date  >= cutoff_28d,
            )
        )
        .order_by(db.DailyStressSummary.summary_date.asc())
    )
    rdy_rows = rdy_res.scalars().all()
    readiness_records = [
        RecoveryRecord(
            date_index=i,
            recovery=float(row.waking_recovery_score or 0.0),
        )
        for i, row in enumerate(rdy_rows)
    ]

    # ── Deviations ────────────────────────────────────────────────────────────
    dev_res = await session.execute(
        select(db.PlanDeviation)
        .where(
            and_(
                db.PlanDeviation.user_id == user_id,
                db.PlanDeviation.ts      >= cutoff_30d,
            )
        )
    )
    dev_rows = dev_res.scalars().all()
    deviation_records = [
        DeviationRecord(
            activity_slug=row.activity_slug,
            priority=row.priority,
            reason_category=row.reason_category,
        )
        for row in dev_rows
    ]

    # ── Adherence by category (last 7 days of DailyPlan items) ───────────────
    cutoff_7d = datetime.now(UTC) - timedelta(days=7)
    plan_res = await session.execute(
        select(db.DailyPlan)
        .where(
            and_(
                db.DailyPlan.user_id   == user_id,
                db.DailyPlan.plan_date >= cutoff_7d,
            )
        )
        .order_by(db.DailyPlan.plan_date.asc())
    )
    plan_rows = plan_res.scalars().all()

    # Build category → (completed, total) tallies from items_json + adherence_pct
    cat_totals: dict[str, list[float]] = {}   # category → list of item adherence values
    for plan_row in plan_rows:
        if not plan_row.items_json:
            continue
        adh = plan_row.adherence_pct or 0.0
        for item in plan_row.items_json:
            cat = item.get("category", "other")
            cat_totals.setdefault(cat, []).append(adh)

    adherence_by_category: dict[str, float] = {
        cat: round(sum(vals) / len(vals), 3)
        for cat, vals in cat_totals.items()
    } if cat_totals else {}

    # ── Tag model (sport stressors) ───────────────────────────────────────────
    tag_res = await session.execute(
        select(db.TagPatternModel).where(db.TagPatternModel.user_id == user_id)
    )
    tag_model = tag_res.scalar_one_or_none()
    sport_stressors: list[str] = []
    if tag_model and tag_model.sport_stressor_slugs:
        sport_stressors = tag_model.sport_stressor_slugs

    # ── Stage ─────────────────────────────────────────────────────────────────
    user_res = await session.execute(
        select(db.User).where(db.User.id == user_id)
    )
    user_row = user_res.scalar_one_or_none()
    current_stage = int(user_row.training_level or 0) if user_row else 0

    return assess_user(
        current_stage=current_stage,
        session_records=session_records,
        readiness_records=readiness_records,
        deviation_records=deviation_records,
        adherence_by_category=adherence_by_category or None,
        sport_stressors=sport_stressors or None,
    )


# ── Per-user rebuild ──────────────────────────────────────────────────────────

async def _rebuild_one_user(
    session,
    user_id,
    llm_client: Optional[Any],
) -> dict:
    """
    Run full rebuild pipeline for one user.
    Returns a dict with rebuild metrics.
    """
    from sqlalchemy import select, and_
    import api.db.schema as db
    from api.services.profile_service import rebuild_unified_profile
    from api.services.psych_service import load_psych_profile
    from api.services.model_service import ModelService
    from api.services.plan_service import PlanService

    result: dict = {
        "user_id": str(user_id),
        "status":  "ok",
        "day_closed":               False,
        "narrative_version":        None,
        "engagement_tier":          None,
        "plan_items":               0,
        "streak_incremented":       False,
        "auto_tagged":              0,
        "capacity_growth_triggered": False,
        "error":                    None,
    }

    try:
        # ── Step 0: Calibration + plan adherence for yesterday ───────────────────
        from api.services.tracking_service import TrackingService
        yesterday = (datetime.now(UTC) - timedelta(days=1)).date()
        try:
            tracking_svc = TrackingService(session, user_id)
            await tracking_svc.run_calibration_for_date(yesterday)
            await tracking_svc.assess_plan_adherence(yesterday)
            result["day_closed"] = True
            log.debug("calibration+adherence OK user=%s date=%s", user_id, yesterday)
        except Exception as exc:
            log.warning("calibration failed user=%s date=%s: %s", user_id, yesterday, exc)
            # Non-fatal — continue with profile rebuild using whatever data exists

        # ── Step 1: Profile rebuild (narrative + plan) ───────────────────────
        # Get today's scores (from most recent DailyStressSummary)
        summary_res = await session.execute(
            select(db.DailyStressSummary)
            .where(db.DailyStressSummary.user_id == user_id)
            .order_by(db.DailyStressSummary.summary_date.desc())
            .limit(1)
        )
        summary = summary_res.scalar_one_or_none()
        net_balance = round(float(summary.net_balance), 1) if summary and summary.net_balance is not None else None
        stress      = int(summary.stress_load_score) if summary and summary.stress_load_score else None
        recovery    = int(summary.waking_recovery_score) if summary and summary.waking_recovery_score else None

        # ── Step 1a: Assessor (behavioural gate + adherence) ──────────────────
        assessment = None
        try:
            assessment = await _run_assessor(session, user_id)
        except Exception as exc:
            log.warning("assessor failed user=%s: %s", user_id, exc)

        # Full rebuild — DataAssembler-powered path (physio injected into Layer 1)
        from profile.profile_updater import run_profile_update
        profile = await run_profile_update(
            session,
            user_id,
            # Disable LLM for Layer 1/2 inside unified_profile rebuild.
            # We will overwrite `coach_narrative` with Phase 4 Layer 2 below
            # using a single dedicated prompt.
            llm_client=None,
            assessment=assessment,
        )
        result["narrative_version"] = profile.narrative_version
        result["engagement_tier"]   = profile.engagement.engagement_tier
        result["plan_items"]        = len(profile.suggested_plan)

        # ── Step 1c: Phase 4 Layer 2 narrative (single call) ────────────────
        # Rebuild `UUP.coach_narrative` using CoachInputPacket + Layer 2 prompt.
        try:
            from coach.input_builder import build_coach_input_packet
            from coach.prompt_templates import build_layer2_narrative_prompt
            from sqlalchemy import select

            packet = await build_coach_input_packet(session, user_id)
            sys_prompt, user_prompt = build_layer2_narrative_prompt(packet)

            if llm_client is not None:
                # Offload sync OpenAI call to a worker thread so the nightly
                # job does not block the event loop (and, by extension, any
                # other cohabiting async tasks in this process).
                raw = await asyncio.to_thread(
                    llm_client.chat, sys_prompt, user_prompt, False
                )
                narrative = (raw or "").strip()
                if not narrative:
                    narrative = _fallback_layer2_narrative(packet)
            else:
                narrative = _fallback_layer2_narrative(packet)

            # Persist Layer 2 narrative + WATCH TODAY bullets
            uup_res = await session.execute(
                select(db.UserUnifiedProfile).where(db.UserUnifiedProfile.user_id == user_id)
            )
            uup_row = uup_res.scalar_one_or_none()
            if uup_row is not None:
                from tracking.cycle_boundaries import local_today
                uup_row.coach_narrative = narrative
                uup_row.coach_narrative_date = local_today()
                uup_row.coach_watch_notes = _extract_watch_today_bullets(narrative)
                await session.commit()
        except Exception as exc:
            log.warning("layer2_narrative failed user=%s error=%s", user_id, exc)

        # ── Step 1b: Materialise today's DailyPlan once/day (IST) ────────────
        # Ensures Plan tab is ready before first user open.
        try:
            model_svc = ModelService(db=session)
            plan_svc = PlanService(db=session, model_service=model_svc, llm_client=llm_client)
            plan_dict = await plan_svc.get_or_create_today_plan(str(user_id), force_regen=True)
            result["plan_items"] = len(plan_dict.get("items", []))
        except Exception as exc:
            log.warning("plan materialisation failed user=%s: %s", user_id, exc)

        # ── Layer 3 coach caches (morning brief + yesterday summary) ─────────
        try:
            from uuid import UUID as _UUID

            from api.db.database import AsyncSessionLocal as _SessionFactory
            from coach.morning_brief import generate_morning_brief
            from coach.yesterday_summary import generate_yesterday_summary

            uid_uuid = user_id if isinstance(user_id, _UUID) else _UUID(str(user_id))
            await generate_morning_brief(_SessionFactory, uid_uuid, llm_client)
            await generate_yesterday_summary(_SessionFactory, uid_uuid, llm_client)
        except Exception as exc:
            log.warning("nightly coach Layer3 cache failed user=%s: %s", user_id, exc)

        # Streak increment
        await _increment_streak(session, user_id)
        result["streak_incremented"] = True

        # Auto-tag pass
        tagged = await _auto_tag_pass(session, user_id)
        result["auto_tagged"] = tagged

        # Capacity growth detection (post-lock only; no-ops pre-calibration)
        growth = await _check_capacity_growth(session, user_id)
        result["capacity_growth_triggered"] = growth["triggered"]
        if growth["triggered"]:
            log.info(
                "nightly_rebuild capacity_growth user=%s new_ceiling=%.1f",
                user_id, growth["new_ceiling"],
            )

    except Exception as exc:
        log.error("nightly_rebuild failed user=%s error=%s", user_id, exc, exc_info=True)
        result["status"] = "error"
        result["error"]  = str(exc)

    return result


# ── Main entry point ──────────────────────────────────────────────────────────

async def run_nightly_rebuild(llm_client: Optional[Any] = None) -> dict:
    """
    Run the full nightly rebuild for all active users.

    Parameters
    ----------
    llm_client : optional
        Injected LLM client. If None, reads config and builds one.
        Pass None in test mode to use fallback (deterministic) path.

    Returns
    -------
    dict with keys: total, succeeded, failed, skipped, duration_seconds
    """
    from api.db.database import AsyncSessionLocal
    from sqlalchemy import text

    started_at = datetime.now(UTC)
    log.info("nightly_rebuild START %s", started_at.isoformat())

    # ── Postgres advisory lock ────────────────────────────────────────────────
    # Every replica's scheduler will race to run this at the same cron tick.
    # A session-scoped advisory lock guarantees only one worker (across the
    # whole DB) executes the job at a time; others bail out quickly.
    _LOCK_KEY = 7431_0001  # arbitrary but stable
    async with AsyncSessionLocal() as lock_session:
        got_lock = (
            await lock_session.execute(
                text("SELECT pg_try_advisory_lock(:k)"), {"k": _LOCK_KEY}
            )
        ).scalar()
        if not got_lock:
            log.info("nightly_rebuild SKIP — another worker holds the advisory lock")
            return {
                "total": 0, "succeeded": 0, "failed": 0, "skipped": 1,
                "duration_seconds": 0.0, "started_at": started_at.isoformat(),
                "reason": "advisory_lock_busy",
            }

        try:
            if llm_client is None:
                llm_client = _build_llm_client()

            succeeded = 0
            failed    = 0
            skipped   = 0
            results   = []

            async with AsyncSessionLocal() as session:
                user_ids = await _get_active_user_ids(session)
                log.info("nightly_rebuild active_users=%d", len(user_ids))

            # Process users with bounded concurrency so long LLM calls
            # overlap but we never spawn an unbounded number of sessions.
            max_concurrent = int(os.getenv("NIGHTLY_REBUILD_CONCURRENCY", "4"))
            sem = asyncio.Semaphore(max(1, max_concurrent))

            async def _run_one(user_id):
                async with sem:
                    async with AsyncSessionLocal() as user_session:
                        return await _rebuild_one_user(user_session, user_id, llm_client)

            tasks = [asyncio.create_task(_run_one(uid)) for uid in user_ids]
            for fut in asyncio.as_completed(tasks):
                try:
                    r = await fut
                except Exception as exc:
                    log.exception("nightly_rebuild user failed: %s", exc)
                    r = {"status": "error", "error": str(exc)}
                results.append(r)
                if r.get("status") == "ok":
                    succeeded += 1
                else:
                    failed += 1

            duration = (datetime.now(UTC) - started_at).total_seconds()
            summary = {
                "total":            len(results),
                "succeeded":        succeeded,
                "failed":           failed,
                "skipped":          skipped,
                "duration_seconds": round(duration, 2),
                "started_at":       started_at.isoformat(),
            }
            log.info("nightly_rebuild END %s", summary)
            return summary
        finally:
            try:
                await lock_session.execute(
                    text("SELECT pg_advisory_unlock(:k)"), {"k": _LOCK_KEY}
                )
                await lock_session.commit()
            except Exception:
                log.warning("nightly_rebuild advisory unlock failed", exc_info=True)


def _build_llm_client() -> Optional[Any]:
    """Build LLM client from environment variables."""
    enabled = os.getenv("LLM_ENABLED", "false").lower() == "true"
    api_key  = os.getenv("OPENAI_API_KEY", "")
    if not enabled or not api_key:
        log.info("nightly_rebuild: LLM disabled — using fallback narrative/plan")
        return None
    try:
        from openai import OpenAI
        return OpenAI(api_key=api_key)
    except ImportError:
        log.warning("openai package not available — using fallback")
        return None


# ── CLI entry point ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    )
    asyncio.run(run_nightly_rebuild())
