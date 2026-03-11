"""
jobs/nightly_rebuild.py

Nightly background job runner.

Runs these tasks sequentially for all active users:
  1. Unified Profile rebuild (Layer 1 narrative + Layer 2 plan + Layer 3 guardrails)
  2. Psych profile streak increment (yesterday's adherence → streak_current)
  3. Auto-tag pass stub (placeholder — pattern model not yet fully wired)

Intended to run once per night (e.g. 02:00 local server time) via cron,
APScheduler, or a cloud scheduler (AWS EventBridge, GCP Cloud Scheduler, etc.).

Usage
-----
Standalone execution (for cron / docker entrypoint):
    python -m jobs.nightly_rebuild

FastAPI APScheduler integration (add to api/main.py lifespan):
    from jobs.nightly_rebuild import run_nightly_rebuild
    scheduler.add_job(run_nightly_rebuild, trigger="cron", hour=2, minute=0)

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
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

log = logging.getLogger(__name__)


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
    all_active = union(session_users, read_users).subquery()

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

    yesterday = (datetime.now(UTC) - timedelta(days=1)).date()
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
    Placeholder for the nightly auto-tag pass.
    Full implementation: iterate untagged StressWindow/RecoveryWindow rows,
    query TagPatternModel, write tag_source='auto_tagged'.
    Returns number of windows newly tagged.
    """
    # TODO: implement full auto-tag pass using TagPatternModel
    return 0


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

    result: dict = {
        "user_id": str(user_id),
        "status":  "ok",
        "day_closed":         False,
        "narrative_version": None,
        "engagement_tier":   None,
        "plan_items":        0,
        "streak_incremented": False,
        "auto_tagged":       0,
        "error":             None,
    }

    try:
        # ── Step 0: Close yesterday's day (write DailyStressSummary) ──────────────
        from api.services.tracking_service import TrackingService
        yesterday = (datetime.now(UTC) - timedelta(days=1)).date()
        try:
            tracking_svc = TrackingService(user_session, user_id)
            await tracking_svc.close_day(yesterday)
            result["day_closed"] = True
            log.debug("close_day OK user=%s date=%s", user_id, yesterday)
        except Exception as exc:
            log.warning("close_day failed user=%s date=%s: %s", user_id, yesterday, exc)
            # Non-fatal — continue with profile rebuild using whatever
            # DailyStressSummary data already exists

        # ── Step 1: Profile rebuild (narrative + plan) ───────────────────────
        # Get today's scores (from most recent DailyStressSummary)
        summary_res = await session.execute(
            select(db.DailyStressSummary)
            .where(db.DailyStressSummary.user_id == user_id)
            .order_by(db.DailyStressSummary.summary_date.desc())
            .limit(1)
        )
        summary = summary_res.scalar_one_or_none()
        readiness = int(summary.readiness_score) if summary and summary.readiness_score else None
        stress    = int(summary.stress_load_score) if summary and summary.stress_load_score else None
        recovery  = int(summary.recovery_score) if summary and summary.recovery_score else None

        # Full rebuild
        profile = await rebuild_unified_profile(
            session,
            user_id,
            llm_client=llm_client,
            readiness_score=readiness,
            stress_score=stress,
            recovery_score=recovery,
        )
        result["narrative_version"] = profile.narrative_version
        result["engagement_tier"]   = profile.engagement.engagement_tier
        result["plan_items"]        = len(profile.suggested_plan)

        # Streak increment
        await _increment_streak(session, user_id)
        result["streak_incremented"] = True

        # Auto-tag pass
        tagged = await _auto_tag_pass(session, user_id)
        result["auto_tagged"] = tagged

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

    started_at = datetime.now(UTC)
    log.info("nightly_rebuild START %s", started_at.isoformat())

    if llm_client is None:
        llm_client = _build_llm_client()

    succeeded = 0
    failed    = 0
    skipped   = 0
    results   = []

    async with AsyncSessionLocal() as session:
        user_ids = await _get_active_user_ids(session)
        log.info("nightly_rebuild active_users=%d", len(user_ids))

        for user_id in user_ids:
            # Use a fresh session per user to isolate failures
            async with AsyncSessionLocal() as user_session:
                r = await _rebuild_one_user(user_session, user_id, llm_client)
                results.append(r)
                if r["status"] == "ok":
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
