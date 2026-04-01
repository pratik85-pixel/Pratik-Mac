"""Morning-reset cycle: recap anchor and current cycle date (stable across IST midnight)."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.services.tracking_service import TrackingService
from tracking.cycle_boundaries import utc_instant_bounds_for_local_calendar_date


@pytest.mark.asyncio
async def test_resolve_strict_recap_anchor_uses_last_reset_when_today_reset_not_fired() -> None:
    """When last_reset < local_today, recap points to last_reset itself."""
    mock_db = AsyncMock()
    uid = "00000000-0000-0000-0000-000000000001"
    fake_user = MagicMock()
    fake_user.last_morning_cycle_reset_local_date = date(2026, 3, 30)
    mock_db.get = AsyncMock(return_value=fake_user)

    svc = TrackingService(mock_db, uid, session_factory=None, llm_client=None)
    with patch("api.services.tracking_service.local_today", return_value=date(2026, 3, 31)):
        recap_d, start_ts, end_ts = await svc.resolve_strict_recap_anchor()

    assert recap_d == date(2026, 3, 30)
    exp_start, exp_end = utc_instant_bounds_for_local_calendar_date(date(2026, 3, 30))
    assert start_ts == exp_start
    assert end_ts == exp_end


@pytest.mark.asyncio
async def test_resolve_strict_recap_anchor_uses_minus_one_when_today_reset_fired() -> None:
    """When last_reset == local_today, recap points to last_reset - 1 day."""
    mock_db = AsyncMock()
    uid = "00000000-0000-0000-0000-000000000001"
    fake_user = MagicMock()
    fake_user.last_morning_cycle_reset_local_date = date(2026, 3, 31)
    mock_db.get = AsyncMock(return_value=fake_user)

    svc = TrackingService(mock_db, uid, session_factory=None, llm_client=None)
    with patch("api.services.tracking_service.local_today", return_value=date(2026, 3, 31)):
        recap_d, _, _ = await svc.resolve_strict_recap_anchor()
    assert recap_d == date(2026, 3, 30)


@pytest.mark.asyncio
async def test_resolve_strict_recap_anchor_stale_last_reset_falls_back_to_yesterday() -> None:
    """If last_reset is older than yesterday, recap must not stay pinned to stale day."""
    mock_db = AsyncMock()
    uid = "00000000-0000-0000-0000-000000000001"
    fake_user = MagicMock()
    fake_user.last_morning_cycle_reset_local_date = date(2026, 3, 29)
    mock_db.get = AsyncMock(return_value=fake_user)

    svc = TrackingService(mock_db, uid, session_factory=None, llm_client=None)
    with patch("api.services.tracking_service.local_today", return_value=date(2026, 3, 31)), patch(
        "api.services.tracking_service.recap_yesterday_local_date",
        return_value=date(2026, 3, 30),
    ):
        recap_d, _, _ = await svc.resolve_strict_recap_anchor()
    assert recap_d == date(2026, 3, 30)


@pytest.mark.asyncio
async def test_resolve_strict_recap_anchor_falls_back_when_no_reset() -> None:
    mock_db = AsyncMock()
    uid = "00000000-0000-0000-0000-000000000001"
    fake_user = MagicMock()
    fake_user.last_morning_cycle_reset_local_date = None
    mock_db.get = AsyncMock(return_value=fake_user)

    svc = TrackingService(mock_db, uid, session_factory=None, llm_client=None)
    fixed = date(2026, 4, 1)
    with patch(
        "api.services.tracking_service.recap_yesterday_local_date",
        return_value=fixed,
    ):
        recap_d, _, _ = await svc.resolve_strict_recap_anchor()
    assert recap_d == fixed


@pytest.mark.asyncio
async def test_get_current_cycle_local_date_returns_last_reset() -> None:
    mock_db = AsyncMock()
    uid = "00000000-0000-0000-0000-000000000001"
    fake_user = MagicMock()
    fake_user.last_morning_cycle_reset_local_date = date(2026, 3, 30)
    mock_db.get = AsyncMock(return_value=fake_user)

    svc = TrackingService(mock_db, uid, session_factory=None, llm_client=None)
    assert await svc.get_current_cycle_local_date() == date(2026, 3, 30)


@pytest.mark.asyncio
async def test_get_current_cycle_local_date_fallback_local_today() -> None:
    mock_db = AsyncMock()
    uid = "00000000-0000-0000-0000-000000000001"
    fake_user = MagicMock()
    fake_user.last_morning_cycle_reset_local_date = None
    mock_db.get = AsyncMock(return_value=fake_user)

    svc = TrackingService(mock_db, uid, session_factory=None, llm_client=None)
    fixed = date(2026, 5, 10)
    with patch("api.services.tracking_service.local_today", return_value=fixed):
        assert await svc.get_current_cycle_local_date() == fixed
