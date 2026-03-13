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
from api.db.schema import Metric, MorningRead, PersonalModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])


# ── Request / Response models ──────────────────────────────────────────────────

class SeedBaselineRequest(BaseModel):
    user_id: str


class SeedBaselineResponse(BaseModel):
    user_id:           str
    rmssd_samples:     int
    morning_samples:   int
    rmssd_floor:       Optional[float]
    rmssd_ceiling:     Optional[float]
    rmssd_morning_avg: Optional[float]
    stress_capacity_floor_rmssd: Optional[float]
    message:           str


# ── Endpoint ───────────────────────────────────────────────────────────────────

@router.post("/seed-baseline", response_model=SeedBaselineResponse)
async def seed_baseline(
    body: SeedBaselineRequest,
    db: AsyncSession = Depends(get_db),
) -> SeedBaselineResponse:
    """
    One-shot test helper: compute and write RMSSD baseline from real recorded data.

    Steps:
    1. Fetch all rmssd rows from `metrics` for this user.
    2. Compute p25 (floor), p75 (ceiling), median (all-day avg).
    3. Fetch morning_reads and compute morning avg separately if available.
    4. Upsert personal_models with those values.
    5. Return computed values so caller can verify.
    """
    try:
        uid = uuid.UUID(body.user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format for user_id")

    # ── 1. Fetch raw RMSSD readings ────────────────────────────────────────────
    result = await db.execute(
        select(Metric.value)
        .where(Metric.user_id == uid)
        .where(Metric.name == "rmssd")
        .order_by(Metric.ts.desc())
        .limit(2000)
    )
    rmssd_values = [row[0] for row in result.fetchall() if row[0] is not None and row[0] > 0]

    if not rmssd_values:
        raise HTTPException(
            status_code=404,
            detail="No rmssd metrics found for this user. Cannot seed baseline."
        )

    logger.info("seed-baseline: %d rmssd samples for user %s", len(rmssd_values), uid)

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
        rmssd_samples=n,
        morning_samples=len(morning_values),
        rmssd_floor=rmssd_floor,
        rmssd_ceiling=rmssd_ceiling,
        rmssd_morning_avg=rmssd_morning_avg,
        stress_capacity_floor_rmssd=capacity_floor,
        message=(
            f"Baseline seeded from {n} rmssd samples "
            f"({len(morning_values)} morning reads). "
            "Now call POST /tracking/close-day to recompute scores."
        ),
    )
