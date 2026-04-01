from __future__ import annotations

import logging
from typing import Annotated, Optional

from fastapi import Depends, Header, HTTPException, Request

from api.config import get_settings

logger = logging.getLogger(__name__)
_cfg = get_settings()


def _jwks_client():
    if not _cfg.JWT_JWKS_URL:
        raise HTTPException(status_code=503, detail="JWT not configured")
    try:
        from jwt import PyJWKClient
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=503, detail="JWT dependencies not installed") from exc
    return PyJWKClient(_cfg.JWT_JWKS_URL)


async def resolve_user_id(
    request: Request,
    x_user_id: Annotated[Optional[str], Header()] = None,
    authorization: Annotated[Optional[str], Header()] = None,
) -> str:
    """
    Resolve caller identity.

    - If ENABLE_JWT_AUTH is true: require Bearer JWT and derive user_id from `sub`.
    - Else: fall back to X-User-Id (intended to be set by a trusted gateway).
    """
    if _cfg.ENABLE_JWT_AUTH:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="Bearer token required")
        token = authorization.split(" ", 1)[1].strip()
        try:
            import jwt
            signing_key = _jwks_client().get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=["RS256"],
                issuer=_cfg.JWT_ISSUER or None,
                audience=_cfg.JWT_AUDIENCE or None,
                options={
                    "require": ["exp", "sub"],
                    "verify_iss": bool(_cfg.JWT_ISSUER),
                    "verify_aud": bool(_cfg.JWT_AUDIENCE),
                },
            )
        except Exception as exc:
            logger.warning("jwt_invalid: %s", exc)
            raise HTTPException(status_code=401, detail="Invalid token")

        sub = str(claims.get("sub") or "").strip()
        if not sub:
            raise HTTPException(status_code=401, detail="Invalid token subject")
        return sub

    # Preserve FastAPI's typical "missing required header" behavior (422) for
    # the legacy header-auth mode, so existing clients/tests keep expectations.
    if not x_user_id:
        raise HTTPException(status_code=422, detail="X-User-Id header required")
    return x_user_id


UserIdDep = Annotated[str, Depends(resolve_user_id)]

