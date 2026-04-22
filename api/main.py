"""
api/main.py

FastAPI application entrypoint.

Startup sequence
----------------
1. Settings are validated via `get_settings()`.
2. Singleton services (SessionService, CoachService, ConversationService)
   are attached to `app.state` so routers can access them via `request.app.state`.
3. All routers are registered with their prefix.
4. CORS and logging middleware are applied.

Run locally:
    .venv/bin/uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging
from time import perf_counter
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from api.config import get_settings
from api.routers import (
    stream,
    session,
    user,
    coach,
    outcomes,
    plan,
    tracking,
    tagging,
    psych,
    profile,
    band_sessions,
    notifications,
    admin,
)
from api.services.session_service import SessionService
from api.services.coach_service import CoachService
from api.services.conversation_service import ConversationService
from api.observability.request_metrics import get_db_query_count, reset_request_metrics

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    _SCHEDULER_AVAILABLE = True
except ImportError:  # pragma: no cover
    _SCHEDULER_AVAILABLE = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
logger  = logging.getLogger(__name__)
_cfg    = get_settings()


# ── LLM client factory ─────────────────────────────────────────────────────────

class _SyncLLMClient:
    """
    Thin synchronous wrapper that matches the duck-typed protocol expected by
    coach_api.generate_response():

        llm_client.chat(system: str, user: str) -> str  (raw JSON string)
    """
    def __init__(self, api_key: str, model: str = "gpt-4o"):
        from openai import OpenAI
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def chat(self, system: str, user: str, json_mode: bool = True) -> str:
        kwargs: dict = {}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            **kwargs,
        )
        return resp.choices[0].message.content or ""


def _build_llm_client():
    """Return an LLM client or None (offline mode)."""
    if not _cfg.LLM_ENABLED or not _cfg.OPENAI_API_KEY:
        logger.info("LLM disabled — using local_engine fallback")
        return None
    try:
        return _SyncLLMClient(api_key=_cfg.OPENAI_API_KEY, model=_cfg.OPENAI_MODEL)
    except ImportError:
        logger.warning("openai package not available — offline mode")
        return None


# ── App lifespan ───────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Startup: instantiate singleton services and attach to app.state.
    Shutdown: any cleanup.
    """
    logger.info("ZenFlow Verity API starting up (debug=%s)", _cfg.DEBUG)

    llm = _build_llm_client()

    app.state.session_service      = SessionService()
    app.state.coach_service        = CoachService(llm_client=llm)
    app.state.conversation_service = ConversationService(llm_client=llm)
    app.state.llm_client           = llm  # shared ref for tracking wake hook

    logger.info("services initialised: session, coach, conversation")

    # ── Nightly scheduler (02:00 UTC) ─────────────────────────────────────────
    scheduler = None
    if _SCHEDULER_AVAILABLE:
        from jobs.nightly_rebuild import run_nightly_rebuild
        scheduler = AsyncIOScheduler(timezone="UTC")
        scheduler.add_job(
            run_nightly_rebuild,
            # 06:30 AM IST == 01:00 UTC (IST is UTC+5:30)
            CronTrigger(hour=1, minute=0, timezone="UTC"),
            id="nightly_rebuild",
            name="Nightly calibration + narrative (01:00 UTC / 06:30 IST)",
            replace_existing=True,
        )
        scheduler.start()
        logger.info("nightly scheduler started — next run 01:00 UTC (06:30 IST)")
    else:
        logger.warning("apscheduler not installed — nightly rebuild will not run automatically")

    yield

    # Graceful shutdown
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("nightly scheduler stopped")
    active = app.state.session_service.active_count()
    if active:
        logger.warning("shutdown with %d active sessions still open", active)
    logger.info("ZenFlow Verity API shut down")


# ── App factory ────────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    app = FastAPI(
        title       = "ZenFlow Verity API",
        description = "Nervous system biofeedback training backend",
        version     = "0.1.0",
        lifespan    = lifespan,
        docs_url    = "/docs" if _cfg.DEBUG else None,
        redoc_url   = "/redoc" if _cfg.DEBUG else None,
    )

    # ── CORS ──────────────────────────────────────────────────────────────────
    # Native mobile apps don't send an Origin header, so an empty list is fine
    # for them. For browser clients, set `CORS_ORIGINS` to an explicit allowlist.
    _origins = _cfg.CORS_ORIGINS
    # `allow_credentials=True` with a wildcard origin is spec-invalid and unsafe,
    # so we drop credentials when origins is "*" (Settings also replaces "*" with
    # [] in production — belt-and-suspenders).
    _allow_credentials = _origins != ["*"] and len(_origins) > 0
    app.add_middleware(
        CORSMiddleware,
        allow_origins     = _origins,
        allow_credentials = _allow_credentials,
        allow_methods     = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers     = ["Authorization", "Content-Type", "X-User-Id", "X-Request-ID"],
    )

    # ── Trusted Host ──────────────────────────────────────────────────────────
    if _cfg.TRUSTED_HOSTS:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(_cfg.TRUSTED_HOSTS))

    @app.middleware("http")
    async def _request_timing_middleware(request: Request, call_next):
        reset_request_metrics()
        started = perf_counter()
        response = await call_next(request)
        duration_ms = (perf_counter() - started) * 1000.0
        logger.info(
            "request_timing method=%s path=%s status=%s duration_ms=%.2f db_queries=%d",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            get_db_query_count(),
        )
        return response

    # ── Routers ───────────────────────────────────────────────────────────────
    if _cfg.ENABLE_WEBSOCKET:
        app.include_router(stream.router)
    app.include_router(session.router)
    app.include_router(user.router)
    app.include_router(coach.router)
    app.include_router(outcomes.router)
    app.include_router(outcomes.router_v1)
    app.include_router(plan.router)
    app.include_router(tracking.router)
    app.include_router(tagging.router)
    app.include_router(psych.router)
    app.include_router(profile.router)
    app.include_router(band_sessions.router)
    app.include_router(notifications.router)
    if _cfg.ENABLE_ADMIN_ENDPOINTS:
        app.include_router(admin.router)

    # ── Health check ──────────────────────────────────────────────────────────
    @app.get("/health", tags=["meta"])
    async def health() -> dict:
        return {
            "status":       "ok",
            "version":      "0.1.0",
            "llm_enabled":  _cfg.LLM_ENABLED,
            "active_sessions": app.state.session_service.active_count(),
        }

    # ── Global error handler ──────────────────────────────────────────────────
    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error on %s: %s", request.url.path, exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "internal server error"},
        )

    return app


app = create_app()
