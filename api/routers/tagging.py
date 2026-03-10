"""
api/routers/tagging.py

Tag management endpoints.

GET  /tagging/tags              — user's recent tag history (stress + recovery)
POST /tagging/tag               — apply a user-confirmed tag to a window
GET  /tagging/patterns          — user's TagPatternModel (patterns + sport stressors)
GET  /tagging/nudge             — untagged windows ready for Tag Sheet nudge
POST /tagging/rebuild-patterns  — force full pattern model rebuild (debug/admin)
"""

from __future__ import annotations

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.database import get_db
from api.services.tagging_service import TaggingService
from api.services.model_service import ModelService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tagging", tags=["tagging"])


# ── Dependencies ──────────────────────────────────────────────────────────────

async def _user_id(x_user_id: Annotated[str, Header()]) -> str:
    if not x_user_id:
        raise HTTPException(status_code=401, detail="X-User-Id header required")
    return x_user_id


async def _tagging_svc(db: AsyncSession = Depends(get_db)) -> TaggingService:
    return TaggingService(db=db)


async def _model_svc(db: AsyncSession = Depends(get_db)) -> ModelService:
    return ModelService(db=db)


# ── Request / response models ─────────────────────────────────────────────────

class TagWindowRequest(BaseModel):
    window_id:   str = Field(..., description="UUID of the StressWindow or RecoveryWindow to tag")
    window_type: str = Field(..., description="'stress' or 'recovery'")
    slug:        str = Field(..., description="Activity catalog slug (e.g. 'workout', 'work_calls')")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/tags")
async def get_tag_history(
    user_id:     str            = Depends(_user_id),
    tagging_svc: TaggingService = Depends(_tagging_svc),
    limit: int  = Query(default=20, ge=1, le=100),
) -> dict:
    """
    Return the user's recent tagged windows (stress + recovery), newest first.

    Each item includes window_id, window_type, started_at, tag, tag_source,
    and suppression_pct (stress windows only).
    """
    history = await tagging_svc.get_tag_history(user_id=user_id, limit=limit)
    return {
        "user_id": user_id,
        "count":   len(history),
        "tags":    history,
    }


@router.post("/tag")
async def tag_window(
    body:        TagWindowRequest,
    user_id:     str            = Depends(_user_id),
    tagging_svc: TaggingService = Depends(_tagging_svc),
) -> dict:
    """
    Apply a user-confirmed tag to a stress or recovery window.

    On success, also incrementally updates the user's TagPatternModel.
    Returns the TagResult (success, tag_applied, error).
    """
    if body.window_type not in ("stress", "recovery"):
        raise HTTPException(
            status_code=422,
            detail="window_type must be 'stress' or 'recovery'",
        )

    result = await tagging_svc.tag_window(
        user_id=user_id,
        window_id=body.window_id,
        window_type=body.window_type,
        slug=body.slug,
    )

    if not result.success:
        raise HTTPException(status_code=400, detail=result.error or "Tag failed")

    return {
        "user_id":     user_id,
        "window_id":   result.window_id,
        "tag_applied": result.tag_applied,
        "tag_source":  result.tag_source,
    }


@router.get("/patterns")
async def get_patterns(
    user_id:     str            = Depends(_user_id),
    tagging_svc: TaggingService = Depends(_tagging_svc),
) -> dict:
    """
    Return the user's current TagPatternModel.

    Includes:
    - patterns: per-tag pattern summaries (confirmed_count, hour_histogram, etc.)
    - sport_stressor_slugs: sports that consistently drive high stress
    - auto_tag_eligible_slugs: tags ready for auto-tagging
    """
    model = await tagging_svc.load_pattern_model(user_id)
    if model is None:
        return {
            "user_id":                user_id,
            "patterns":               {},
            "sport_stressor_slugs":   [],
            "auto_tag_eligible_slugs": [],
        }

    return {
        "user_id":                user_id,
        "patterns":               model.to_dict()["patterns"],
        "sport_stressor_slugs":   model.sport_stressor_slugs,
        "auto_tag_eligible_slugs": list(model.auto_tag_eligible_slugs),
    }


@router.get("/nudge")
async def get_nudge_queue(
    user_id:     str            = Depends(_user_id),
    tagging_svc: TaggingService = Depends(_tagging_svc),
    max_items: int = Query(default=3, ge=1, le=10),
) -> dict:
    """
    Return the top untagged windows for the Tag Sheet nudge UI.

    Ordered by:
      1. Highest suppression_pct (most informative)
      2. Most recent as tiebreaker
    """
    queue = await tagging_svc.get_nudge_queue(user_id=user_id, max_items=max_items)
    return {
        "user_id": user_id,
        "count":   len(queue),
        "nudge_queue": [
            {
                "window_id":       w.window_id,
                "window_type":     w.window_type,
                "started_at":      w.started_at.isoformat(),
                "suppression_pct": w.suppression_pct,
                "tag_candidate":   None,   # UI may show a suggested slug here
            }
            for w in queue
        ],
    }


@router.post("/rebuild-patterns")
async def rebuild_patterns(
    user_id:     str            = Depends(_user_id),
    tagging_svc: TaggingService = Depends(_tagging_svc),
) -> dict:
    """
    Force a full rebuild of the user's TagPatternModel from all confirmed windows.

    Normally triggered automatically.  Exposed here for admin / debug use.
    Returns patterns_built count and sport_stressor_slugs.
    """
    result = await tagging_svc.rebuild_pattern_model(user_id)
    return {
        "user_id":              user_id,
        "patterns_built":       result.patterns_built,
        "sport_stressor_slugs": result.sport_stressors,
    }
