"""
api/routers/profile.py

REST endpoints for the Unified User Profile layer.

Endpoints
---------
  GET  /profile/unified       — get the current UnifiedProfile (or 404)
  POST /profile/rebuild       — trigger a full rebuild (idempotent)
  GET  /profile/facts         — list durable facts for the user
  POST /profile/facts         — manually log a fact
  GET  /profile/engagement    — engagement metrics snapshot

Auth: X-User-Id header (UUID).
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.database import get_db
from api.db.schema import User
from api.utils import parse_uuid
from api.services.profile_service import (
    load_unified_profile,
    rebuild_unified_profile,
    load_facts,
    log_fact,
    compute_engagement_counts,
)
from profile.fact_extractor import ExtractedFact

router = APIRouter(prefix="/profile", tags=["profile"])

# Valid fact categories constant (defined in profile_schema via this import)
_VALID_CATEGORIES = {"person", "preference", "schedule", "event", "goal", "belief", "health"}


# ── Request / Response models ─────────────────────────────────────────────────

class RebuildRequest(BaseModel):
    stress_score:    Optional[int] = Field(None, ge=0, le=100)
    recovery_score:  Optional[int] = Field(None, ge=0, le=100)


class RebuildResponse(BaseModel):
    status:           str
    narrative_version: int
    data_confidence:  float
    engagement_tier:  Optional[str]
    plan_item_count:  int
    guardrail_notes:  list[str]


class FactRequest(BaseModel):
    category:   str = Field(..., description="person|preference|schedule|event|goal|belief|health")
    fact_text:  str = Field(..., max_length=200)
    fact_key:   Optional[str] = Field(None, max_length=60)
    fact_value: Optional[str] = Field(None, max_length=200)
    polarity:   str = Field("neutral", pattern="^(positive|negative|neutral)$")


class FactResponse(BaseModel):
    status:    str
    fact_id:   str
    fact_text: str


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _resolve_user(x_user_id: str = Header(...)) -> uuid.UUID:
    uid = parse_uuid(x_user_id)
    if uid is None:
        raise HTTPException(422, "Invalid X-User-Id")
    return uid


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/unified", response_class=JSONResponse)
async def get_unified_profile(
    db: AsyncSession = Depends(get_db),
    user_id: uuid.UUID = Depends(_resolve_user),
):
    """
    Return the current persisted UnifiedProfile for this user.
    404 if no profile has been built yet (trigger /profile/rebuild first).
    """
    profile = await load_unified_profile(db, user_id)
    if profile is None:
        raise HTTPException(404, "No unified profile found — trigger /profile/rebuild")
    return profile.to_dict()


@router.post("/rebuild", response_model=RebuildResponse, status_code=200)
async def trigger_rebuild(
    body: RebuildRequest,
    db: AsyncSession = Depends(get_db),
    user_id: uuid.UUID = Depends(_resolve_user),
    request: Request = None,
):
    """
    Trigger a full profile rebuild.
    Idempotent — safe to call multiple times.
    Auto-creates the user row if it doesn't exist yet.
    """
    # Ensure the user row exists (FK requirement for all child tables)
    result = await db.execute(select(User).where(User.id == user_id))
    if result.scalar_one_or_none() is None:
        db.add(User(id=user_id, name="User"))
        await db.flush()

    llm_client = None
    if request is not None:
        llm_client = getattr(getattr(request, "app", None), "state", None)
        if llm_client is not None:
            llm_client = getattr(llm_client, "llm_client", None)

    profile = await rebuild_unified_profile(
        db,
        user_id,
        llm_client=llm_client,
        stress_score=body.stress_score,
        recovery_score=body.recovery_score,
    )
    return RebuildResponse(
        status="ok",
        narrative_version=profile.narrative_version,
        data_confidence=profile.data_confidence,
        engagement_tier=profile.engagement.engagement_tier,
        plan_item_count=len(profile.suggested_plan),
        guardrail_notes=profile.plan_guardrail_notes,
    )


@router.get("/facts", response_class=JSONResponse)
async def get_facts(
    min_confidence: float = 0.3,
    db: AsyncSession = Depends(get_db),
    user_id: uuid.UUID = Depends(_resolve_user),
):
    """Return durable facts for this user sorted by confidence."""
    facts = await load_facts(db, user_id, min_confidence=min_confidence)
    return {
        "facts": [
            {
                "fact_id":       f.fact_id,
                "category":      f.category,
                "fact_text":     f.fact_text,
                "polarity":      f.polarity,
                "confidence":    f.confidence,
                "confirmed":     f.user_confirmed,
            }
            for f in facts
        ]
    }


@router.post("/facts", response_model=FactResponse, status_code=201)
async def log_user_fact(
    body: FactRequest,
    db: AsyncSession = Depends(get_db),
    user_id: uuid.UUID = Depends(_resolve_user),
):
    """Manually log a durable fact about the user."""
    if body.category not in _VALID_CATEGORIES:
        raise HTTPException(422, f"Invalid category. Must be one of: {sorted(_VALID_CATEGORIES)}")
    ef = ExtractedFact(
        category=body.category,
        fact_text=body.fact_text,
        fact_key=body.fact_key,
        fact_value=body.fact_value,
        polarity=body.polarity,
        confidence=0.7,  # manual entry starts at higher confidence
    )
    fact_id = await log_fact(db, user_id, ef)
    return FactResponse(status="created", fact_id=fact_id, fact_text=body.fact_text)


@router.get("/engagement", response_class=JSONResponse)
async def get_engagement_snapshot(
    db: AsyncSession = Depends(get_db),
    user_id: uuid.UUID = Depends(_resolve_user),
):
    """
    Return live engagement metrics computed from DB.
    Useful for debugging and product analytics.
    """
    counts = await compute_engagement_counts(db, user_id)
    return counts
