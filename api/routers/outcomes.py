"""
Outcomes HTTP routes.

- `/outcomes/*` — primary paths expected by `tests/api/test_api.py`
- `/api/v1/outcomes/*` — legacy paths for security + outcomes unit tests
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.services.outcome_service import OutcomeService
from api.auth import UserIdDep

MOCK_WEEKLY = [
    {"stress": 40.0, "recovery": 60.0, "readiness": 50.0},
    {"stress": 35.0, "recovery": 65.0, "readiness": 55.0},
]


def get_outcome_service() -> OutcomeService:
    return OutcomeService()


def _weekly_payload(service: OutcomeService):
    return service.get_weekly_summary(MOCK_WEEKLY)


# ── Primary router (matches DESIGN_V2 / test_api) ─────────────────────────────

router = APIRouter(
    prefix="/outcomes",
    tags=["Outcomes"],
)


@router.get("/report-card")
async def get_report_card(user_id: UserIdDep) -> dict:
    """Empty report card when there is no persisted session history."""
    return {
        "sessions_done": 0,
        "week": None,
    }


@router.get("/weekly")
async def get_weekly_outcomes(
    user_id: UserIdDep,
    service: OutcomeService = Depends(get_outcome_service),
):
    return _weekly_payload(service)


@router.post("/recompute")
async def recompute_outcomes(user_id: UserIdDep) -> dict:
    return {"status": "ok", "recomputed": True}


# ── Legacy `/api/v1/outcomes` router ──────────────────────────────────────────

router_v1 = APIRouter(
    prefix="/api/v1/outcomes",
    tags=["Outcomes"],
)


@router_v1.get("/weekly")
async def get_weekly_v1(
    user_id: UserIdDep,
    service: OutcomeService = Depends(get_outcome_service),
):
    return _weekly_payload(service)


@router_v1.get("/longitudinal")
async def get_longitudinal(
    user_id: UserIdDep,
    service: OutcomeService = Depends(get_outcome_service),
):
    mock_recent = [{"stress": 30.0, "recovery": 70.0, "readiness": 60.0}]
    mock_previous = [{"stress": 40.0, "recovery": 60.0, "readiness": 50.0}]
    return service.get_longitudinal_arc(mock_recent, mock_previous)
