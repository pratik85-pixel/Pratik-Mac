"""Midnight IST: strict recap must not advance to a partial (still-open) cycle day."""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.services.tracking_service import TrackingService
from tracking.cycle_boundaries import utc_instant_bounds_for_local_calendar_date


@pytest.mark.asyncio
async def test_midnight_case1_reset_fired_today_recap_is_prior_day() -> None:
    """23:55 same calendar day as last reset → recap = last_reset - 1."""
    mock_db = AsyncMock()
    uid = "00000000-0000-4000-8000-000000000001"
    fake_user = MagicMock()
    fake_user.last_morning_cycle_reset_local_date = date(2026, 4, 10)
    mock_db.get = AsyncMock(return_value=fake_user)

    svc = TrackingService(mock_db, uid, session_factory=None, llm_client=None)
    with patch("api.services.tracking_service.local_today", return_value=date(2026, 4, 10)):
        recap_d, start_ts, end_ts = await svc.resolve_strict_recap_anchor()
    assert recap_d == date(2026, 4, 9)
    exp_s, exp_e = utc_instant_bounds_for_local_calendar_date(date(2026, 4, 9))
    assert start_ts == exp_s and end_ts == exp_e


@pytest.mark.asyncio
async def test_midnight_case2_after_midnight_partial_row_no_recap() -> None:
    """00:05 next day, reset still on prior calendar day, row partial → None."""
    mock_db = AsyncMock()
    uid = "00000000-0000-4000-8000-000000000001"
    fake_user = MagicMock()
    fake_user.last_morning_cycle_reset_local_date = date(2026, 4, 9)
    mock_db.get = AsyncMock(return_value=fake_user)

    row = MagicMock()
    row.is_partial_data = True

    svc = TrackingService(mock_db, uid, session_factory=None, llm_client=None)
    with patch("api.services.tracking_service.local_today", return_value=date(2026, 4, 10)), patch.object(
        TrackingService, "_load_day_summary", new_callable=AsyncMock, return_value=row,
    ):
        recap_d, s, e = await svc.resolve_strict_recap_anchor()
    assert recap_d is None and s is None and e is None


@pytest.mark.asyncio
async def test_midnight_case3_after_midnight_finalized_row_recap_ok() -> None:
    """00:05 next day, yesterday row finalized → recap = that closed day."""
    mock_db = AsyncMock()
    uid = "00000000-0000-4000-8000-000000000001"
    fake_user = MagicMock()
    fake_user.last_morning_cycle_reset_local_date = date(2026, 4, 9)
    mock_db.get = AsyncMock(return_value=fake_user)

    row = MagicMock()
    row.is_partial_data = False

    svc = TrackingService(mock_db, uid, session_factory=None, llm_client=None)
    with patch("api.services.tracking_service.local_today", return_value=date(2026, 4, 10)), patch.object(
        TrackingService, "_load_day_summary", new_callable=AsyncMock, return_value=row,
    ):
        recap_d, _, _ = await svc.resolve_strict_recap_anchor()
    assert recap_d == date(2026, 4, 9)


@pytest.mark.asyncio
async def test_midnight_case4_morning_reset_fired_today_recap_prior() -> None:
    """08:00 with today's reset already fired → recap = yesterday."""
    mock_db = AsyncMock()
    uid = "00000000-0000-4000-8000-000000000001"
    fake_user = MagicMock()
    fake_user.last_morning_cycle_reset_local_date = date(2026, 4, 10)
    mock_db.get = AsyncMock(return_value=fake_user)

    svc = TrackingService(mock_db, uid, session_factory=None, llm_client=None)
    with patch("api.services.tracking_service.local_today", return_value=date(2026, 4, 10)):
        recap_d, _, _ = await svc.resolve_strict_recap_anchor()
    assert recap_d == date(2026, 4, 9)
