"""
Strict recap row + morning bundle (brief/plan) gating.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.services.tracking_service import TrackingService


@pytest.mark.asyncio
async def test_get_morning_recap_summary_none_without_db_row() -> None:
    """No DailyStressSummary for strict IST day → summary None (no snapshot fallback)."""
    mock_db = AsyncMock()
    uid = "00000000-0000-0000-0000-000000000001"

    async def fake_execute(stmt):
        r = MagicMock()
        if "morning_recap_ack_for_date" in str(stmt):
            r.one_or_none = MagicMock(return_value=(None,))
        return r

    mock_db.execute = AsyncMock(side_effect=fake_execute)

    svc = TrackingService(mock_db, uid, session_factory=None, llm_client=None)

    with patch.object(
        TrackingService,
        "resolve_strict_recap_anchor",
        new=AsyncMock(return_value=(date(2026, 3, 28), None, None)),
    ), patch.object(
        TrackingService,
        "load_strict_recap_daily_row",
        new=AsyncMock(return_value=None),
    ):
        out = await svc.get_morning_recap()

    assert out["for_date"] == "2026-03-28"
    assert out["summary"] is None
    assert out["should_show"] is False


@pytest.mark.asyncio
async def test_has_strict_yesterday_summary_true_when_row_present() -> None:
    mock_db = AsyncMock()
    uid = "00000000-0000-0000-0000-000000000001"
    fake_row = MagicMock()
    fake_row.stress_load_score = 10.0

    svc = TrackingService(mock_db, uid, session_factory=None, llm_client=None)

    with patch.object(
        TrackingService,
        "load_strict_recap_daily_row",
        new=AsyncMock(return_value=fake_row),
    ):
        assert await svc.has_strict_yesterday_summary() is True


@pytest.mark.asyncio
async def test_has_strict_yesterday_summary_false_when_row_absent() -> None:
    mock_db = AsyncMock()
    uid = "00000000-0000-0000-0000-000000000001"
    svc = TrackingService(mock_db, uid, session_factory=None, llm_client=None)

    with patch.object(
        TrackingService,
        "load_strict_recap_daily_row",
        new=AsyncMock(return_value=None),
    ):
        assert await svc.has_strict_yesterday_summary() is False
