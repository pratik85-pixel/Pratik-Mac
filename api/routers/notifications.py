"""
api/routers/notifications.py

Strict v1 notification APIs.

GET  /v1/notifications/feed
POST /v1/notifications/action
POST /v1/notifications/checkin
POST /v1/notifications/dismiss
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

import api.db.schema as db_schema
from api.db.database import get_db
from api.services.notification_policy_service import NotificationPolicyService
from api.utils import parse_uuid

router = APIRouter(prefix="/v1/notifications", tags=["notifications"])


async def _user_id(x_user_id: Annotated[str, Header()]) -> str:
    if not x_user_id:
        raise HTTPException(status_code=401, detail="X-User-Id header required")
    return x_user_id


class NotificationActionRequest(BaseModel):
    notification_id: str
    action_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    acted_at: Optional[datetime] = None


class NotificationCheckinRequest(BaseModel):
    notification_id: str
    responses: dict[str, Any]
    submitted_at: Optional[datetime] = None


class NotificationDismissRequest(BaseModel):
    notification_id: str
    dismissed_at: Optional[datetime] = None


class DeviceTokenRequest(BaseModel):
    token: str = Field(..., min_length=10, max_length=255)
    platform: Optional[str] = Field(default=None, description="ios | android")


@router.get("/feed")
async def get_feed(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: Optional[str] = Query(default=None),
    since: Optional[datetime] = Query(default=None),
    user_id: str = Depends(_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    svc = NotificationPolicyService(
        db,
        user_id,
        llm_client=getattr(request.app.state, "llm_client", None),
    )
    return await svc.get_feed(limit=limit, cursor=cursor, since=since)


@router.post("/action")
async def post_action(
    body: NotificationActionRequest,
    user_id: str = Depends(_user_id),
    db: AsyncSession = Depends(get_db),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    svc = NotificationPolicyService(db, user_id)
    acted_at = body.acted_at.astimezone(UTC) if body.acted_at else datetime.now(UTC)
    res = await svc.apply_action(
        notification_id=body.notification_id,
        action_type=body.action_type,
        payload=body.payload,
        acted_at=acted_at,
        idempotency_key=idempotency_key,
    )
    if not res.get("ok"):
        code = str((res.get("error") or {}).get("code") or "")
        status = 400
        if code == "unauthorized":
            status = 401
        elif code == "not_found":
            status = 404
        elif code == "conflict":
            status = 409
        elif code == "validation_error":
            status = 422
        raise HTTPException(status_code=status, detail=res["error"]["message"])
    return res


@router.post("/checkin")
async def post_checkin(
    body: NotificationCheckinRequest,
    user_id: str = Depends(_user_id),
    db: AsyncSession = Depends(get_db),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    svc = NotificationPolicyService(db, user_id)
    submitted_at = body.submitted_at.astimezone(UTC) if body.submitted_at else datetime.now(UTC)
    res = await svc.submit_checkin(
        notification_id=body.notification_id,
        responses=body.responses,
        submitted_at=submitted_at,
        idempotency_key=idempotency_key,
    )
    if not res.get("ok"):
        code = str((res.get("error") or {}).get("code") or "")
        status = 400
        if code == "unauthorized":
            status = 401
        elif code == "not_found":
            status = 404
        elif code == "conflict":
            status = 409
        elif code == "validation_error":
            status = 422
        raise HTTPException(status_code=status, detail=res["error"]["message"])
    return {
        "ok": True,
        "saved": bool(res.get("effects", {}).get("checkin_saved")),
        "coach_refresh_queued": bool(res.get("effects", {}).get("coach_refresh_queued")),
    }


@router.post("/dismiss")
async def dismiss_notification(
    body: NotificationDismissRequest,
    user_id: str = Depends(_user_id),
    db: AsyncSession = Depends(get_db),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    svc = NotificationPolicyService(db, user_id)
    dismissed_at = body.dismissed_at.astimezone(UTC) if body.dismissed_at else datetime.now(UTC)
    res = await svc.dismiss(
        notification_id=body.notification_id,
        dismissed_at=dismissed_at,
        idempotency_key=idempotency_key,
    )
    if not res.get("ok"):
        code = str((res.get("error") or {}).get("code") or "")
        status = 400
        if code == "unauthorized":
            status = 401
        elif code == "not_found":
            status = 404
        elif code == "conflict":
            status = 409
        elif code == "validation_error":
            status = 422
        raise HTTPException(status_code=status, detail=res["error"]["message"])
    return {"ok": True, "notification_id": body.notification_id, "dismissed": True}


@router.post("/device-token")
async def register_device_token(
    body: DeviceTokenRequest,
    user_id: str = Depends(_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    uid = parse_uuid(user_id)
    if uid is None:
        raise HTTPException(status_code=401, detail="Invalid X-User-Id")
    row = await db.get(db_schema.User, uid)
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    row.push_token = body.token.strip()
    row.push_platform = (body.platform or "").strip().lower() or None
    row.push_token_updated_at = datetime.now(UTC)
    await db.commit()
    return {"ok": True}
