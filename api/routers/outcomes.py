"""
api/routers/outcomes.py

Outcome and report-card endpoints.

GET  /outcomes/report-card     — weekly report card (the main user-facing summary)
GET  /outcomes/weekly          — raw weekly aggregates
POST /outcomes/recompute       — trigger a re-computation of weekly outcomes
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.database import get_db
from api.services.model_service import ModelService
from api.services.outcome_service import OutcomeService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/outcomes", tags=["outcomes"])


# ── Dependencies ───────────────────────────────────────────────────────────────

async def _user_id(x_user_id: Annotated[str, Header()]) -> str:
    if not x_user_id:
        raise HTTPException(status_code=401, detail="X-User-Id header required")
    return x_user_id

async def _model_svc(db: AsyncSession = Depends(get_db)) -> ModelService:
    return ModelService(db=db)

async def _outcome_svc(
    db:        AsyncSession = Depends(get_db),
    model_svc: ModelService = Depends(_model_svc),
) -> OutcomeService:
    return OutcomeService(model_service=model_svc, db=db)


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/report-card")
async def report_card(
    user_id:     str            = Depends(_user_id),
    outcome_svc: OutcomeService = Depends(_outcome_svc),
) -> dict:
    """
    Return the most recent weekly report card.
    On first call (or if stale), recomputes from raw session data.
    """
    return await outcome_svc.get_report_card(user_id)


@router.get("/weekly")
async def weekly_outcomes(
    user_id:     str            = Depends(_user_id),
    outcome_svc: OutcomeService = Depends(_outcome_svc),
) -> dict:
    """Compute (or return cached) weekly outcome aggregates."""
    return await outcome_svc.compute_weekly_report(user_id)


@router.post("/recompute")
async def recompute(
    user_id:     str            = Depends(_user_id),
    outcome_svc: OutcomeService = Depends(_outcome_svc),
) -> dict:
    """Force a re-computation of weekly outcomes for this user."""
    report = await outcome_svc.compute_weekly_report(user_id)
    return {"recomputed": True, "report": report}
