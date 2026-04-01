"""
api/routers/band_sessions.py

Band wear session endpoints.

GET /band-sessions/history           — list of closed band wear sessions (newest first)
GET /band-sessions/current           — the current open band wear session (if any)
GET /band-sessions/{id}              — summary detail for a single session
GET /band-sessions/{id}/metrics      — RMSSD/HR metrics, events, personal baseline, sparkline
GET /band-sessions/{id}/plan         — daily plan adherence for the session date
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, desc, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import UserIdDep
from api.db.database import get_db
from api.db import schema as db
from api.utils import parse_uuid

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/band-sessions", tags=["band-sessions"])


# ── Auth dependency ────────────────────────────────────────────────────────────


# ── Response models ────────────────────────────────────────────────────────────

class BandSessionSummary(BaseModel):
    id:                str
    started_at:        str
    ended_at:          Optional[str]
    is_closed:         bool
    duration_minutes:  Optional[float]
    stress_pct:        Optional[float]
    recovery_pct:      Optional[float]
    net_balance:       Optional[float]
    has_sleep_data:    bool
    opening_balance:   float
    # Pre-computed metrics (available once session is closed)
    avg_rmssd_ms:      Optional[float]
    avg_hr_bpm:        Optional[float]


class BandSessionDetail(BaseModel):
    id:                     str
    started_at:             str
    ended_at:               Optional[str]
    is_closed:              bool
    duration_minutes:       Optional[float]
    stress_pct:             Optional[float]
    recovery_pct:           Optional[float]
    net_balance:            Optional[float]
    has_sleep_data:         bool
    opening_balance:        float
    opening_balance_locked: bool
    avg_rmssd_ms:           Optional[float]
    avg_hr_bpm:             Optional[float]
    sleep_rmssd_avg_ms:     Optional[float]
    sleep_started_at:       Optional[str]
    sleep_ended_at:         Optional[str]


# ── Metrics endpoint models ────────────────────────────────────────────────────

class StressEventItem(BaseModel):
    id:                      str
    started_at:              str
    ended_at:                str
    duration_minutes:        float
    tag:                     Optional[str]
    tag_candidate:           Optional[str]
    tag_source:              Optional[str]
    suppression_pct:         Optional[float]
    stress_contribution_pct: Optional[float]


class RecoveryEventItem(BaseModel):
    id:                       str
    started_at:               str
    ended_at:                 str
    duration_minutes:         float
    context:                  str
    tag:                      Optional[str]
    rmssd_avg_ms:             Optional[float]
    recovery_contribution_pct: Optional[float]


class SparklinePoint(BaseModel):
    ts:       str          # ISO timestamp (window_start)
    rmssd_ms: Optional[float]
    context:  str          # "background" | "sleep"


class PersonalBaseline(BaseModel):
    rmssd_morning_avg:  Optional[float]
    rmssd_floor:        Optional[float]
    rmssd_ceiling:      Optional[float]
    rmssd_sleep_avg:    Optional[float]
    prf_bpm:            Optional[float]   # personal resting HR


class BandSessionMetrics(BaseModel):
    session_id:          str
    # Pre-computed aggregates (from band_wear_sessions row)
    avg_rmssd_ms:        Optional[float]
    avg_hr_bpm:          Optional[float]
    sleep_rmssd_avg_ms:  Optional[float]
    sleep_started_at:    Optional[str]
    sleep_ended_at:      Optional[str]
    sleep_duration_minutes: Optional[float]
    # Events within the session range
    stress_events:       List[StressEventItem]
    recovery_events:     List[RecoveryEventItem]
    # RMSSD sparkline — all valid windows in session range, ordered by time
    sparkline:           List[SparklinePoint]
    # Personal baseline from personal_models
    personal:            PersonalBaseline


# ── Plan endpoint models ───────────────────────────────────────────────────────

class PlanItem(BaseModel):
    slug:         str
    display:      str
    category:     Optional[str]
    priority:     str          # "must_do" | "recommended" | "optional"
    duration_min: Optional[int]
    completed:    bool


class BandSessionPlan(BaseModel):
    session_id:    str
    plan_date:     Optional[str]   # ISO date, None if no plan exists
    has_plan:      bool
    adherence_pct: Optional[float]
    items:         List[PlanItem]  # only completed items (no deviation exists)
    total_items:   int             # total planned items (for context)


# ── Serialisation helpers ──────────────────────────────────────────────────────

def _to_summary(row: db.BandWearSession) -> BandSessionSummary:
    duration: Optional[float] = None
    if row.started_at and row.ended_at:
        duration = round((row.ended_at - row.started_at).total_seconds() / 60.0, 1)
    return BandSessionSummary(
        id               = str(row.id),
        started_at       = row.started_at.isoformat(),
        ended_at         = row.ended_at.isoformat() if row.ended_at else None,
        is_closed        = row.is_closed,
        duration_minutes = duration,
        stress_pct       = round(row.stress_pct, 1)      if row.stress_pct      is not None else None,
        recovery_pct     = round(row.recovery_pct, 1)    if row.recovery_pct    is not None else None,
        net_balance      = round(row.net_balance, 2)      if row.net_balance     is not None else None,
        has_sleep_data   = row.has_sleep_data,
        opening_balance  = round(row.opening_balance, 2),
        avg_rmssd_ms     = round(row.avg_rmssd_ms, 1)    if row.avg_rmssd_ms    is not None else None,
        avg_hr_bpm       = round(row.avg_hr_bpm, 1)      if row.avg_hr_bpm      is not None else None,
    )


def _to_detail(row: db.BandWearSession) -> BandSessionDetail:
    duration: Optional[float] = None
    if row.started_at and row.ended_at:
        duration = round((row.ended_at - row.started_at).total_seconds() / 60.0, 1)

    sleep_dur: Optional[float] = None
    if row.sleep_started_at and row.sleep_ended_at:
        sleep_dur = round(
            (row.sleep_ended_at - row.sleep_started_at).total_seconds() / 60.0, 1
        )

    return BandSessionDetail(
        id                      = str(row.id),
        started_at              = row.started_at.isoformat(),
        ended_at                = row.ended_at.isoformat() if row.ended_at else None,
        is_closed               = row.is_closed,
        duration_minutes        = duration,
        stress_pct              = round(row.stress_pct, 1)          if row.stress_pct          is not None else None,
        recovery_pct            = round(row.recovery_pct, 1)        if row.recovery_pct        is not None else None,
        net_balance             = round(row.net_balance, 2)          if row.net_balance         is not None else None,
        has_sleep_data          = row.has_sleep_data,
        opening_balance         = round(row.opening_balance, 2),
        opening_balance_locked  = row.opening_balance_locked,
        avg_rmssd_ms            = round(row.avg_rmssd_ms, 1)        if row.avg_rmssd_ms        is not None else None,
        avg_hr_bpm              = round(row.avg_hr_bpm, 1)          if row.avg_hr_bpm          is not None else None,
        sleep_rmssd_avg_ms      = round(row.sleep_rmssd_avg_ms, 1)  if row.sleep_rmssd_avg_ms  is not None else None,
        sleep_started_at        = row.sleep_started_at.isoformat()  if row.sleep_started_at    is not None else None,
        sleep_ended_at          = row.sleep_ended_at.isoformat()    if row.sleep_ended_at      is not None else None,
    )


async def _get_session_or_404(
    session_id: str,
    user_id: str,
    db_sess: AsyncSession,
) -> db.BandWearSession:
    sid = parse_uuid(session_id)
    uid = parse_uuid(user_id)
    if sid is None or uid is None:
        raise HTTPException(status_code=400, detail="invalid id")
    result = await db_sess.execute(
        select(db.BandWearSession)
        .where(db.BandWearSession.id == sid)
        .where(db.BandWearSession.user_id == uid)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="band session not found")
    return row


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/history", response_model=list[BandSessionSummary])
async def get_band_session_history(
    user_id: UserIdDep,
    db_sess: AsyncSession = Depends(get_db),
    limit:   int          = 20,
) -> list[BandSessionSummary]:
    """Return the N most recent closed band wear sessions, newest first."""
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="limit must be 1–200")

    uid = parse_uuid(user_id)
    if uid is None:
        raise HTTPException(status_code=400, detail="invalid user id")

    result = await db_sess.execute(
        select(db.BandWearSession)
        .where(db.BandWearSession.user_id == uid)
        .where(db.BandWearSession.is_closed == True)   # noqa: E712
        .order_by(desc(db.BandWearSession.started_at))
        .limit(limit)
    )
    rows = result.scalars().all()
    return [_to_summary(r) for r in rows]


@router.get("/current", response_model=Optional[BandSessionSummary])
async def get_current_band_session(
    user_id: UserIdDep,
    db_sess: AsyncSession = Depends(get_db),
) -> Optional[BandSessionSummary]:
    """Return the currently open band wear session, or null if band is not worn."""
    uid = parse_uuid(user_id)
    if uid is None:
        raise HTTPException(status_code=400, detail="invalid user id")

    result = await db_sess.execute(
        select(db.BandWearSession)
        .where(db.BandWearSession.user_id == uid)
        .where(db.BandWearSession.is_closed == False)  # noqa: E712
        .order_by(desc(db.BandWearSession.started_at))
        .limit(1)
    )
    row = result.scalar_one_or_none()
    return _to_summary(row) if row else None


@router.get("/{session_id}/metrics", response_model=BandSessionMetrics)
async def get_band_session_metrics(
    session_id: str,
    user_id:    UserIdDep,
    db_sess:    AsyncSession = Depends(get_db),
) -> BandSessionMetrics:
    """
    Return detailed metrics for a single band wear session.

    Includes:
    - Pre-computed RMSSD / HR / sleep aggregates (written at session close)
    - All stress and recovery events within the session time range
    - RMSSD sparkline (one point per background_window, ordered chronologically)
    - User's personal baseline from personal_models (for zone benchmarking)
    """
    session = await _get_session_or_404(session_id, user_id, db_sess)
    uid     = parse_uuid(user_id)

    session_start = session.started_at
    session_end   = session.ended_at
    if session_end is None:
        raise HTTPException(status_code=422, detail="session is still open — metrics not yet finalised")

    # ── Stress events in range ──────────────────────────────────────────────
    stress_res = await db_sess.execute(
        select(db.StressWindow)
        .where(db.StressWindow.user_id == uid)
        .where(db.StressWindow.started_at >= session_start)
        .where(db.StressWindow.started_at < session_end)
        .order_by(db.StressWindow.started_at)
    )
    stress_rows = stress_res.scalars().all()
    stress_events = [
        StressEventItem(
            id                      = str(r.id),
            started_at              = r.started_at.isoformat(),
            ended_at                = r.ended_at.isoformat(),
            duration_minutes        = r.duration_minutes,
            tag                     = r.tag,
            tag_candidate           = r.tag_candidate,
            tag_source              = r.tag_source,
            suppression_pct         = round(r.suppression_pct, 2)         if r.suppression_pct         is not None else None,
            stress_contribution_pct = round(r.stress_contribution_pct, 1) if r.stress_contribution_pct is not None else None,
        )
        for r in stress_rows
    ]

    # ── Recovery events in range ────────────────────────────────────────────
    recovery_res = await db_sess.execute(
        select(db.RecoveryWindow)
        .where(db.RecoveryWindow.user_id == uid)
        .where(db.RecoveryWindow.started_at >= session_start)
        .where(db.RecoveryWindow.started_at < session_end)
        .order_by(db.RecoveryWindow.started_at)
    )
    recovery_rows = recovery_res.scalars().all()
    recovery_events = [
        RecoveryEventItem(
            id                        = str(r.id),
            started_at                = r.started_at.isoformat(),
            ended_at                  = r.ended_at.isoformat(),
            duration_minutes          = r.duration_minutes,
            context                   = r.context,
            tag                       = r.tag,
            rmssd_avg_ms              = round(r.rmssd_avg_ms, 1)              if r.rmssd_avg_ms              is not None else None,
            recovery_contribution_pct = round(r.recovery_contribution_pct, 1) if r.recovery_contribution_pct is not None else None,
        )
        for r in recovery_rows
    ]

    # ── RMSSD sparkline — all valid background_windows in session range ─────
    sparkline_res = await db_sess.execute(
        select(db.BackgroundWindow)
        .where(db.BackgroundWindow.user_id == uid)
        .where(db.BackgroundWindow.window_start >= session_start)
        .where(db.BackgroundWindow.window_start < session_end)
        .where(db.BackgroundWindow.is_valid == True)   # noqa: E712
        .order_by(db.BackgroundWindow.window_start)
    )
    sparkline_rows = sparkline_res.scalars().all()
    sparkline = [
        SparklinePoint(
            ts       = r.window_start.isoformat(),
            rmssd_ms = round(r.rmssd_ms, 1) if r.rmssd_ms is not None else None,
            context  = r.context,
        )
        for r in sparkline_rows
    ]

    # ── Personal baseline ───────────────────────────────────────────────────
    personal_res = await db_sess.execute(
        select(db.PersonalModel)
        .where(db.PersonalModel.user_id == uid)
        .order_by(desc(db.PersonalModel.updated_at))
        .limit(1)
    )
    personal_row = personal_res.scalar_one_or_none()
    personal = PersonalBaseline(
        rmssd_morning_avg = round(personal_row.rmssd_morning_avg, 1) if personal_row and personal_row.rmssd_morning_avg is not None else None,
        rmssd_floor       = round(personal_row.rmssd_floor, 1)       if personal_row and personal_row.rmssd_floor       is not None else None,
        rmssd_ceiling     = round(personal_row.rmssd_ceiling, 1)     if personal_row and personal_row.rmssd_ceiling     is not None else None,
        rmssd_sleep_avg   = round(personal_row.rmssd_sleep_avg, 1)   if personal_row and personal_row.rmssd_sleep_avg   is not None else None,
        prf_bpm           = round(personal_row.prf_bpm, 1)           if personal_row and personal_row.prf_bpm           is not None else None,
    )

    # ── Sleep duration from pre-computed columns ────────────────────────────
    sleep_dur: Optional[float] = None
    if session.sleep_started_at and session.sleep_ended_at:
        sleep_dur = round(
            (session.sleep_ended_at - session.sleep_started_at).total_seconds() / 60.0, 1
        )

    return BandSessionMetrics(
        session_id           = str(session.id),
        avg_rmssd_ms         = round(session.avg_rmssd_ms, 1)       if session.avg_rmssd_ms       is not None else None,
        avg_hr_bpm           = round(session.avg_hr_bpm, 1)         if session.avg_hr_bpm         is not None else None,
        sleep_rmssd_avg_ms   = round(session.sleep_rmssd_avg_ms, 1) if session.sleep_rmssd_avg_ms is not None else None,
        sleep_started_at     = session.sleep_started_at.isoformat() if session.sleep_started_at   is not None else None,
        sleep_ended_at       = session.sleep_ended_at.isoformat()   if session.sleep_ended_at     is not None else None,
        sleep_duration_minutes = sleep_dur,
        stress_events        = stress_events,
        recovery_events      = recovery_events,
        sparkline            = sparkline,
        personal             = personal,
    )


@router.get("/{session_id}/plan", response_model=BandSessionPlan)
async def get_band_session_plan(
    session_id: str,
    user_id:    UserIdDep,
    db_sess:    AsyncSession = Depends(get_db),
) -> BandSessionPlan:
    """
    Return plan adherence for the calendar date of the band session.

    Returns only items that were completed (no PlanDeviation exists for their
    slug). If no daily_plan exists for the session date, has_plan=False and
    items=[] are returned rather than a 404.
    """
    session = await _get_session_or_404(session_id, user_id, db_sess)
    uid     = parse_uuid(user_id)

    # Match on calendar date of session start (date-only comparison via cast)
    session_date: date = session.started_at.date()

    plan_res = await db_sess.execute(
        select(db.DailyPlan)
        .where(db.DailyPlan.user_id == uid)
        .where(func.date(db.DailyPlan.plan_date) == session_date)
        .limit(1)
    )
    plan_row = plan_res.scalar_one_or_none()

    if plan_row is None:
        return BandSessionPlan(
            session_id    = str(session.id),
            plan_date     = None,
            has_plan      = False,
            adherence_pct = None,
            items         = [],
            total_items   = 0,
        )

    # Fetch deviation slugs for this plan
    dev_res = await db_sess.execute(
        select(db.PlanDeviation.activity_slug)
        .where(db.PlanDeviation.plan_id == plan_row.id)
    )
    missed_slugs = {row[0] for row in dev_res.all()}

    # Build item list — only completed items (no deviation for slug)
    raw_items: list = plan_row.items_json or []
    completed_items: List[PlanItem] = []
    for item in raw_items:
        slug = item.get("slug", "")
        if slug not in missed_slugs:
            completed_items.append(PlanItem(
                slug         = slug,
                display      = item.get("display", slug),
                category     = item.get("category"),
                priority     = item.get("priority", "optional"),
                duration_min = item.get("duration_min"),
                completed    = True,
            ))

    return BandSessionPlan(
        session_id    = str(session.id),
        plan_date     = session_date.isoformat(),
        has_plan      = True,
        adherence_pct = round(plan_row.adherence_pct, 1) if plan_row.adherence_pct is not None else None,
        items         = completed_items,
        total_items   = len(raw_items),
    )


@router.get("/{session_id}", response_model=BandSessionDetail)
async def get_band_session_detail(
    session_id: str,
    user_id:    UserIdDep,
    db_sess:    AsyncSession = Depends(get_db),
) -> BandSessionDetail:
    """Return summary detail fields for a single band wear session."""
    session = await _get_session_or_404(session_id, user_id, db_sess)
    return _to_detail(session)
