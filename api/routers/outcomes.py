from fastapi import APIRouter, Depends, Header, HTTPException
from api.services.outcome_service import OutcomeService

router = APIRouter(
    prefix="/api/v1/outcomes",
    tags=["Outcomes"]
)

def get_outcome_service():
    return OutcomeService()

@router.get("/weekly")
async def get_weekly(x_user_id: str = Header(...), service: OutcomeService = Depends(get_outcome_service)):
    mock_data = [
        {"stress": 40.0, "recovery": 60.0, "readiness": 50.0},
        {"stress": 35.0, "recovery": 65.0, "readiness": 55.0},
    ]
    return service.get_weekly_summary(mock_data)

@router.get("/longitudinal")
async def get_longitudinal(x_user_id: str = Header(...), service: OutcomeService = Depends(get_outcome_service)):
    mock_recent = [{"stress": 30.0, "recovery": 70.0, "readiness": 60.0}]
    mock_previous = [{"stress": 40.0, "recovery": 60.0, "readiness": 50.0}]
    return service.get_longitudinal_arc(mock_recent, mock_previous)
