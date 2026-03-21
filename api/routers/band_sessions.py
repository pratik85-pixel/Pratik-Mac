"""
api/routers/band_sessions.py

Band wear session endpoints.

GET /band-sessions/history      — list of closed band wear sessions (newest first)
GET /band-sessions/current      — the current open band wear session (if any)
GET /band-sessions/{id}         — detail for a single session (placeholder)
"""

from __future__ import annotations

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.database import get_db
from api.db import schema as db
from api.utils import parse_uuid

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/band-sessions", tags=["band-sessions"])


# ── Auth dependency ────────────────────────────────────────────────────────────

async def _user_id(x_user_id: Annotated[str, Header()]) -> str:
    if not x_user_id:
        raise HTTPException(status_code=401, detail="X-User-Id header required")
    return x_user_id


# ── Response models ────────────────────────────────────────────────────────────

class BandSessionSummary(BaseModel):
    id:              str
    started_at:      str
    ended_at:        Optional[str]
    is_closed:       bool
    duration_minutes: Optional[float]
    stress_pct:      Optional[float]
    recovery_pct:    Optional[float]
    net_balance:     Optional[float]
    has_sleep_data:  bool
    opening_balance: float


class BandSessionDetail(BaseModel):
    """Placeholder — detailed screen fields to be designed later."""
    id:              str
    started_at:      str
    ended_at:        Optional[str]
    is_closed:       bool
    duration_minutes: Optional[float]
    stress_pct:      Optional[float]
    recovery_pct:    Optional[float]
    net_balance:     Optional[float]
    has_sleep_data:  bool
    opening_balance: float
    opening_balance_locked: bool


def _to_summary(row: db.BandWearSession) -> BandSessionSummary:
    duration: Optional[float] = None
    if row.started_at and row.ended_at:
        duration = round((row.ended_at - row.started_at).total_seconds() / 60.0, 1)
    return BandSessionSummary(
        id              = str(row.id),
        started_at      = row.started_at.isoformat(),
        ended_at        = row.ended_at.isoformat() if row.ended_at else None,
        is_closed       = row.is_closed,
        duration_minutes = duration,
        stress_pct      = round(row.stress_pct, 1) if row.stress_pct is not None else None,
        recovery_pct    = round(row.recovery_pct, 1) if row.recovery_pct is not None else None,
        net_balance     = round(row.net_balance, 2) if row.net_balance is not None else None,
        has_sleep_data  = row.has_sleep_data,
        opening_balance = round(row.opening_balance, 2),
    )


def _to_detail(row: db.BandWearSession) -> BandSessionDetail:
    duration: Optional[float] = None
    if row.started_at and row.ended_at:
        duration = round((row.ended_at - row.started_at).total_seconds() / 60.0, 1)
    return BandSessionDetail(
        id              = str(row.id),
        started_at      = row.started_at.isoformat(),
        ended_at        = row.ended_at.isoformat() if row.ended_at else None,
        is_closed       = row.is_closed,
        duration_minutes = duration,
        stress_pct      = round(row.stress_pct, 1) if row.stress_pct is not None else None,
        recovery_pct    = round(row.recovery_pct, 1) if row.recovery_pct is not None else None,
        net_balance     = round(row.net_balance, 2) if row.net_balance is not None else None,
        has_sleep_data  = row.has_sleep_data,
        opening_balance = round(row.opening_balance, 2),
        opening_balance_locked = row.opening_balance_locked,
    )


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/history", response_model=list[BandSessionSummary])
async def get_band_session_history(
    user_id: str          = Depends(_user_id),
    db_sess: AsyncSession = Depends(get_db),
    limit:   int          = 20,
) -> list[BandSessionSummary]:
    """
    Return the N most recent band wear sessions (closed only), newest first.

    One row = one continuous wear period. A session closes when the band is
    not detected for >90 minutes. Final stress%, recovery%, net_balance and
    has_sleep_data reflect the full wear period at the moment of close.
    """
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=400, detail="limit must be 1–200")

    uid = parse_uuid(user_id)
    if uid is None:
        raise HTTPException(status_code=400, detail="invalid user id")

    result = await db_sess.execute(
        select(db.BandWearSession)
        .where(db.BandWearSession.user_id == uid)
        .where(db.BandWearSession.is_closed == True)  # noqa: E712
        .order_by(desc(db.BandWearSession.started_at))
        .limit(limit)
    )
    rows = result.scalars().all()
    return [_to_summary(r) for r in rows]


@router.get("/current", response_model=Optional[BandSessionSummary])
async def get_current_band_session(
    user_id: str          = Depends(_user_id),
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
    if row is None:
        return None
    return _to_summary(row)


@router.get("/{session_id}", response_model=BandSessionDetail)
async def get_band_session_detail(
    session_id: str,
    user_id:    str          = Depends(_user_id),
    db_sess:    AsyncSession = Depends(get_db),
) -> BandSessionDetail:
    """
    Return full detail for a single band wear session.

    The detail screen is a placeholder — extended fields (events, plan adherence,
    etc.) will be wired in a future design pass.
    """
    uid = parse_uuid(user_id)
    if uid is None:
        raise HTTPException(status_code=400, detail="invalid user id")

    sid = parse_uuid(session_id)
    if sid is None:
        raise HTTPException(status_code=400, detail="invalid session id")

    result = await db_sess.execute(
        select(db.BandWearSession)
        .where(db.BandWearSession.id == sid)
        .where(db.BandWearSession.user_id == uid)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="band session not found")
    return _to_detail(row)
