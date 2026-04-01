"""
Async orchestration for morning bundle side-effects.

Keeps plan regeneration + morning brief dispatch outside TrackingService so the
tracking core can focus on ingest and scoring responsibilities.
"""

from __future__ import annotations

import asyncio
import logging
import uuid as uuid_mod
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_MORNING_BUNDLE_SEM = asyncio.Semaphore(4)


class MorningBundleOrchestrator:
    """Schedules morning plan/brief refresh work for one user."""

    def __init__(self, session_factory: Optional[Callable[..., Any]], llm_client: Optional[Any]) -> None:
        self._session_factory = session_factory
        self._llm_client = llm_client

    def schedule(self, user_id: str) -> None:
        if self._session_factory is None:
            return

        async def _runner() -> None:
            async with _MORNING_BUNDLE_SEM:
                try:
                    async with self._session_factory() as session:
                        from api.services.model_service import ModelService
                        from api.services.plan_service import PlanService
                        from api.services.tracking_service import TrackingService

                        track_svc = TrackingService(
                            session,
                            user_id,
                            session_factory=self._session_factory,
                            llm_client=self._llm_client,
                        )
                        model_svc = ModelService(session)
                        plan_svc = PlanService(session, model_svc)
                        recap = await track_svc.get_morning_recap()
                        if recap.get("summary"):
                            await plan_svc.get_or_create_today_plan(user_id, force_regen=True)
                        else:
                            await plan_svc.delete_today_plan_if_exists(user_id)
                except Exception as exc:
                    logger.warning(
                        "Morning bundle: plan regen failed user=%s: %s",
                        user_id,
                        exc,
                        exc_info=True,
                    )

                from coach.morning_brief import generate_morning_brief

                await generate_morning_brief(
                    self._session_factory,
                    uuid_mod.UUID(str(user_id)),
                    self._llm_client,
                )

        asyncio.create_task(_runner())
