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
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.config import get_settings
from api.routers import stream, session, user, coach, outcomes, plan, tracking, tagging, psych, profile
from api.services.session_service import SessionService
from api.services.coach_service import CoachService
from api.services.conversation_service import ConversationService

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

    def chat(self, system: str, user: str) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            response_format={"type": "json_object"},
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

    logger.info("services initialised: session, coach, conversation")

    # ── Nightly scheduler (02:00 UTC) ─────────────────────────────────────────
    scheduler = None
    if _SCHEDULER_AVAILABLE:
        from jobs.nightly_rebuild import run_nightly_rebuild
        scheduler = AsyncIOScheduler(timezone="UTC")
        scheduler.add_job(
            run_nightly_rebuild,
            CronTrigger(hour=18, minute=30, timezone="UTC"),  # 00:00 IST midnight fallback
            id="nightly_rebuild",
            name="Nightly rebuild + close_day (18:30 UTC / 00:00 IST midnight)",
            replace_existing=True,
        )
        scheduler.start()
        logger.info("nightly scheduler started — next run 18:30 UTC (00:00 IST midnight)")
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
    app.add_middleware(
        CORSMiddleware,
        allow_origins     = _cfg.CORS_ORIGINS,
        allow_credentials = True,
        allow_methods     = ["*"],
        allow_headers     = ["*"],
    )

    # ── Routers ───────────────────────────────────────────────────────────────
    if _cfg.ENABLE_WEBSOCKET:
        app.include_router(stream.router)
    app.include_router(session.router)
    app.include_router(user.router)
    app.include_router(coach.router)
    app.include_router(outcomes.router)
    app.include_router(plan.router)
    app.include_router(tracking.router)
    app.include_router(tagging.router)
    app.include_router(psych.router)
    app.include_router(profile.router)

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
