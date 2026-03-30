"""
api/services/push_service.py

Best-effort Expo push sender for notification events.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import api.db.schema as db

logger = logging.getLogger(__name__)

_EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


def _looks_like_expo_token(token: str) -> bool:
    t = (token or "").strip()
    return t.startswith("ExponentPushToken[") or t.startswith("ExpoPushToken[")


async def send_expo_push_for_user(
    db_session: AsyncSession,
    *,
    user_uuid,
    title: str,
    body: Optional[str],
    data: Optional[dict[str, Any]] = None,
) -> bool:
    """
    Send an Expo push for a user if a token exists.

    Returns True when accepted by Expo API, else False.
    """
    user_row = (
        await db_session.execute(
            select(db.User).where(db.User.id == user_uuid).limit(1)
        )
    ).scalar_one_or_none()
    if user_row is None:
        return False

    token = (user_row.push_token or "").strip()
    if not token or not _looks_like_expo_token(token):
        return False

    payload = {
        "to": token,
        "title": title,
        "body": body or "",
        "sound": "default",
        "priority": "high",
        "data": data or {},
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(_EXPO_PUSH_URL, json=payload)
        if resp.status_code >= 300:
            logger.warning(
                "Expo push rejected user=%s status=%s body=%s",
                str(user_uuid),
                resp.status_code,
                resp.text[:400],
            )
            return False
        # Mark last successful send timestamp on the user token row.
        user_row.push_token_updated_at = datetime.now(UTC)
        await db_session.commit()
        return True
    except Exception:
        logger.exception("Expo push send failed user=%s", str(user_uuid))
        return False
