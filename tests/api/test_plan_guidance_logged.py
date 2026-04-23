"""Plan Layer3 logs failures instead of swallowing silently."""

from __future__ import annotations

import logging
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.services.model_service import ModelService
from api.services.plan_service import PlanService


@pytest.mark.asyncio
async def test_plan_layer3_llm_exception_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR)
    db = AsyncMock()
    uid = uuid.uuid4()

    class _BadLLM:
        def chat(self, *_a, **_k):
            raise RuntimeError("simulated LLM failure")

    svc = PlanService(db=db, model_service=MagicMock(spec=ModelService), llm_client=_BadLLM())
    with patch(
        "coach.input_builder.build_coach_input_packet",
        new_callable=AsyncMock,
        return_value=MagicMock(),
    ), patch(
        "coach.prompt_templates.build_layer3_plan_brief_prompt",
        return_value=("sys", "user"),
    ):
        out = await svc._maybe_add_layer3_plan_brief_and_donts(
            user_id=str(uid),
            uid=uid,
            payload_items=[],
            payload_day_type=None,
            narrative="x" * 200,
        )
    assert out["brief"] is None
    assert "plan brief Layer3 failed" in caplog.text
