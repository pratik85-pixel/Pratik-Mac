"""
api/routers/admin.py

TEMPORARY testing-only endpoint — remove after baseline is seeded.

POST /admin/seed-baseline
    Reads real RMSSD values from the metrics table for a given user,
    computes floor / ceiling / morning-avg, writes them into personal_models,
    and returns the computed values so you can verify before re-running close-day.
"""

from __future__ import annotations

import logging
import statistics
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.database import get_db
from api.db.schema import BackgroundWindow, Metric, MorningRead, PersonalModel, Session

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])


# ── Request / Response models ──────────────────────────────────────────────────

class SeedBaselineRequest(BaseModel):
    user_id: str


class SeedBaselineResponse(BaseModel):
    user_id:                     str
    bg_window_samples:           int
    metric_samples:              int
    session_samples:             int
    morning_samples:             int
    rmssd_floor:                 Optional[float]
    rmssd_ceiling:               Optional[float]
    rmssd_morning_avg:           Optional[float]
    stress_capacity_floor_rmssd: Optional[float]
    message:                     str


class DebugDataResponse(BaseModel):
    user_id:               str
    metric_rows:           int
    background_window_rows: int
    session_rows:          int
    morning_rows:          int
    sample_rmssd_values:   list[float]
    sample_bg_rmssd:       list[float]
    sample_session_rmssd:  list[float]


# ── Endpoint ───────────────────────────────────────────────────────────────────

@router.get("/debug/{user_id}", response_model=DebugDataResponse)
async def debug_user_data(
    user_id: str,
    db: AsyncSession = Depends(get_db),
) -> DebugDataResponse:
    """Quick probe — shows how many rows exist per table for this user."""
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")

    metric_result = await db.execute(
        select(Metric.value)
        .where(Metric.user_id == uid)
        .where(Metric.name == "rmssd")
        .limit(10)
    )
    metric_vals = [r[0] for r in metric_result.fetchall()]

    bg_result = await db.execute(
        select(BackgroundWindow.rmssd_ms)
        .where(BackgroundWindow.user_id == uid)
        .where(BackgroundWindow.rmssd_ms.isnot(None))
        .order_by(BackgroundWindow.window_start.desc())
        .limit(10)
    )
    bg_vals = [r[0] for r in bg_result.fetchall() if r[0]]

    bg_count_result = await db.execute(
        select(BackgroundWindow.rmssd_ms)
        .where(BackgroundWindow.user_id == uid)
    )
    bg_total = len(bg_count_result.fetchall())

    session_result = await db.execute(
        select(Session.rmssd_pre, Session.rmssd_post)
        .where(Session.user_id == uid)
        .limit(20)
    )
    session_rmssd = [v for row in session_result.fetchall() for v in [row[0], row[1]] if v]

    morning_result = await db.execute(
        select(MorningRead.rmssd_ms)
        .where(MorningRead.user_id == uid)
        .where(MorningRead.rmssd_ms.isnot(None))
        .limit(10)
    )
    morning_rows = morning_result.fetchall()

    all_metrics_count = await db.execute(
        select(Metric.name)
        .where(Metric.user_id == uid)
    )
    total_metric_rows = len(all_metrics_count.fetchall())

    return DebugDataResponse(
        user_id=user_id,
        metric_rows=total_metric_rows,
        background_window_rows=bg_total,
        session_rows=len(session_rmssd) // 2,
        morning_rows=len(morning_rows),
        sample_rmssd_values=metric_vals[:5],
        sample_bg_rmssd=bg_vals[:8],
        sample_session_rmssd=session_rmssd[:10],
    )


@router.post("/seed-baseline", response_model=SeedBaselineResponse)
async def seed_baseline(
    body: SeedBaselineRequest,
    db: AsyncSession = Depends(get_db),
) -> SeedBaselineResponse:
    """
    One-shot test helper: compute and write RMSSD baseline from real recorded data.

    Steps:
    1. Fetch all rmssd rows from `metrics` for this user.
    2. Fall back to rmssd_pre/rmssd_post from `sessions` if metrics table is empty.
    3. Compute p10 (floor), p90 (ceiling), median (all-day avg).
    4. Fetch morning_reads and compute morning avg separately if available.
    5. Upsert personal_models with those values.
    6. Return computed values so caller can verify.
    """
    try:
        uid = uuid.UUID(body.user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format for user_id")

    # ── 1. background_windows (primary) ───────────────────────────────────────
    bg_result = await db.execute(
        select(BackgroundWindow.rmssd_ms)
        .where(BackgroundWindow.user_id == uid)
        .where(BackgroundWindow.rmssd_ms.isnot(None))
        .order_by(BackgroundWindow.window_start.desc())
        .limit(2000)
    )
    rmssd_values = [r[0] for r in bg_result.fetchall() if r[0] and r[0] > 0]
    bg_count = len(rmssd_values)

    # ── 2. metrics table ──────────────────────────────────────────────────────
    metric_result = await db.execute(
        select(Metric.value)
        .where(Metric.user_id == uid)
        .where(Metric.name == "rmssd")
        .order_by(Metric.ts.desc())
        .limit(2000)
    )
    metric_vals = [r[0] for r in metric_result.fetchall() if r[0] and r[0] > 0]
    rmssd_values.extend(metric_vals)
    metric_count = len(metric_vals)

    # ── 3. session fallback ───────────────────────────────────────────────────
    session_rmssd_count = 0
    if not rmssd_values:
        sess_result = await db.execute(
            select(Session.rmssd_pre, Session.rmssd_post)
            .where(Session.user_id == uid)
        )
        for row in sess_result.fetchall():
            for v in [row[0], row[1]]:
                if v and v > 0:
                    rmssd_values.append(v)
                    session_rmssd_count += 1

    if not rmssd_values:
        raise HTTPException(
            status_code=404,
            detail=(
                "No RMSSD data found in background_windows, metrics, or sessions. "
                "The app must flush at least one 5-min background window first."
            )
        )

    logger.info(
        "seed-baseline: user=%s total=%d (bg=%d metric=%d session=%d)",
        uid, len(rmssd_values), bg_count, metric_count, session_rmssd_count,
    )

    # ── 2. Compute all-day stats ───────────────────────────────────────────────
    sorted_vals = sorted(rmssd_values)
    n = len(sorted_vals)

    def percentile(data: list[float], p: float) -> float:
        k = (len(data) - 1) * p / 100
        lo, hi = int(k), min(int(k) + 1, len(data) - 1)
        return data[lo] + (data[hi] - data[lo]) * (k - lo)

    rmssd_floor   = round(percentile(sorted_vals, 10), 1)   # p10 — low stress floor
    rmssd_ceiling = round(percentile(sorted_vals, 90), 1)   # p90 — high recovery ceiling
    rmssd_all_avg = round(statistics.median(sorted_vals), 1)

    # Capacity floor uses p25 for stress normalisation (slightly more conservative)
    capacity_floor = round(percentile(sorted_vals, 25), 1)

    # ── 3. Morning reads (if available) ───────────────────────────────────────
    morning_result = await db.execute(
        select(MorningRead.rmssd_ms)
        .where(MorningRead.user_id == uid)
        .where(MorningRead.rmssd_ms.isnot(None))
        .order_by(MorningRead.read_date.desc())
        .limit(60)
    )
    morning_values = [row[0] for row in morning_result.fetchall() if row[0] and row[0] > 0]

    rmssd_morning_avg = (
        round(statistics.median(morning_values), 1) if morning_values
        else rmssd_all_avg
    )

    logger.info(
        "seed-baseline computed: floor=%.1f ceiling=%.1f morning_avg=%.1f "
        "(from %d morning reads, falling back to all-day median)",
        rmssd_floor, rmssd_ceiling, rmssd_morning_avg,
        len(morning_values),
    )

    # ── 4. Upsert personal_models ──────────────────────────────────────────────
    existing = await db.execute(
        select(PersonalModel).where(PersonalModel.user_id == uid)
    )
    model_row = existing.scalar_one_or_none()

    if model_row is None:
        # Create new row
        model_row = PersonalModel(
            user_id=uid,
            rmssd_floor=rmssd_floor,
            rmssd_ceiling=rmssd_ceiling,
            rmssd_morning_avg=rmssd_morning_avg,
            stress_capacity_floor_rmssd=capacity_floor,
        )
        db.add(model_row)
        logger.info("seed-baseline: created new PersonalModel row for user %s", uid)
    else:
        # Update existing row in-place
        model_row.rmssd_floor                = rmssd_floor
        model_row.rmssd_ceiling              = rmssd_ceiling
        model_row.rmssd_morning_avg          = rmssd_morning_avg
        model_row.stress_capacity_floor_rmssd = capacity_floor
        logger.info("seed-baseline: updated existing PersonalModel row for user %s", uid)

    await db.commit()

    return SeedBaselineResponse(
        user_id=body.user_id,
        bg_window_samples=bg_count,
        metric_samples=metric_count,
        session_samples=session_rmssd_count,
        morning_samples=len(morning_values),
        rmssd_floor=rmssd_floor,
        rmssd_ceiling=rmssd_ceiling,
        rmssd_morning_avg=rmssd_morning_avg,
        stress_capacity_floor_rmssd=capacity_floor,
        message=(
            f"Baseline seeded from {n} samples "
            f"({bg_count} bg windows + {metric_count} metrics + {session_rmssd_count} sessions, "
            f"{len(morning_values)} morning reads). "
            "Now call POST /tracking/close-day to recompute scores."
        ),
    )
