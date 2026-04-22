"""
api/auth.py

Caller-identity resolution.

Modes
-----
1. JWT (recommended for production):
   - Set `ENABLE_JWT_AUTH=True` + `JWT_JWKS_URL` (+ optional issuer/audience).
   - Clients must send `Authorization: Bearer <token>`; `sub` becomes the user id.

2. Header fallback (development / trusted gateway only):
   - `X-User-Id: <id>` is used as the caller identity.
   - This path is disabled automatically in production (`ENVIRONMENT != dev`
     and `DEBUG != true`) — see `api/config._enforce_production_defaults`.

The `PyJWKClient` is cached at module level so JWKS keys are fetched once
per process and reused across requests.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Annotated, Optional

from fastapi import Depends, Header, HTTPException, Request

from api.config import get_settings

logger = logging.getLogger(__name__)
_cfg = get_settings()


@lru_cache(maxsize=1)
def _jwks_client():
    """Singleton PyJWKClient — JWKS keys are fetched once and cached by PyJWT."""
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
    Resolve the caller identity.

    Order of precedence:
    1. If `ENABLE_JWT_AUTH` is true → require Bearer JWT, derive user id from `sub`.
    2. Else if `ALLOW_HEADER_AUTH` is true → fall back to `X-User-Id`.
    3. Otherwise → 401.

    In production `ALLOW_HEADER_AUTH` is forced to `False` when JWT is enabled
    (see `Settings._enforce_production_defaults`), so the header fallback
    cannot be used to impersonate users.
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
                leeway=max(0, int(_cfg.JWT_LEEWAY_SECONDS)),
                options={
                    "require": ["exp", "sub"],
                    "verify_iss": bool(_cfg.JWT_ISSUER),
                    "verify_aud": bool(_cfg.JWT_AUDIENCE),
                },
            )
        except Exception as exc:
            # Log at DEBUG to avoid leaking parser detail at INFO/WARN in prod.
            logger.debug("jwt_invalid: %s", exc)
            raise HTTPException(status_code=401, detail="Invalid token")

        sub = str(claims.get("sub") or "").strip()
        if not sub:
            raise HTTPException(status_code=401, detail="Invalid token subject")
        return sub

    if not _cfg.ALLOW_HEADER_AUTH:
        # JWT disabled and header-auth disabled → no way to identify the caller.
        raise HTTPException(
            status_code=401,
            detail="Authentication is required (configure ENABLE_JWT_AUTH)",
        )

    # Preserve FastAPI's "missing required header" behaviour (422) for the
    # legacy header-auth mode so existing clients/tests keep expectations.
    if not x_user_id:
        raise HTTPException(status_code=422, detail="X-User-Id header required")
    return x_user_id


UserIdDep = Annotated[str, Depends(resolve_user_id)]
