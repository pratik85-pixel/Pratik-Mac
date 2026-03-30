"""Tests for Scenario B (no overnight wear) forced morning reset + anchor helper."""

from __future__ import annotations

import asyncio
import uuid as uuid_mod
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock

from zoneinfo import ZoneInfo

from api.services.tracking_service import (
    anchor_utc_for_local_calendar_date,
)


def test_anchor_utc_for_local_calendar_date_default_7am_ist():
    d = date(2026, 2, 5)
    utc = anchor_utc_for_local_calendar_date(d, None, "Asia/Kolkata")
    # Feb 5 07:00 IST = Feb 5 01:30 UTC
    assert utc.hour == 1 and utc.minute == 30
    assert utc.date() == date(2026, 2, 5)


def test_anchor_utc_for_local_calendar_date_custom_wake():
    d = date(2026, 2, 5)
    utc = anchor_utc_for_local_calendar_date(d, "08:30", "Asia/Kolkata")
    # Feb 5 08:30 IST = Feb 5 03:00 UTC
    assert utc.hour == 3 and utc.minute == 0


def _run(coro):
    return asyncio.run(coro)


def test_scenario_b_false_before_anchor():
    from api.services.tracking_service import TrackingService

    uid = uuid_mod.uuid4()
    user = MagicMock()
    user.last_morning_cycle_reset_local_date = None
    personal = MagicMock()
    personal.typical_wake_time = "07:00"

    ist = ZoneInfo("Asia/Kolkata")
    window_start = datetime(2026, 2, 5, 6, 30, tzinfo=ist).astimezone(UTC)

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=user)

    svc = TrackingService(mock_db, str(uid), session_factory=None)
    ok, d = _run(svc._should_perform_scenario_b_forced_reset(window_start, personal))
    assert ok is False
    assert d is None
    mock_db.execute.assert_not_called()


def test_scenario_b_false_when_already_reset_today():
    from api.services.tracking_service import TrackingService

    uid = uuid_mod.uuid4()
    user = MagicMock()
    user.last_morning_cycle_reset_local_date = date(2026, 2, 5)
    personal = MagicMock()
    personal.typical_wake_time = "07:00"

    ist = ZoneInfo("Asia/Kolkata")
    window_start = datetime(2026, 2, 5, 11, 30, tzinfo=ist).astimezone(UTC)

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=user)

    svc = TrackingService(mock_db, str(uid), session_factory=None)
    ok, d = _run(svc._should_perform_scenario_b_forced_reset(window_start, personal))
    assert ok is False
    assert d is None
    mock_db.execute.assert_not_called()


def test_scenario_b_false_when_inter_anchor_has_window():
    from api.services.tracking_service import TrackingService

    uid = uuid_mod.uuid4()
    user = MagicMock()
    user.last_morning_cycle_reset_local_date = None
    personal = MagicMock()
    personal.typical_wake_time = "07:00"

    ist = ZoneInfo("Asia/Kolkata")
    window_start = datetime(2026, 2, 5, 11, 30, tzinfo=ist).astimezone(UTC)

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=user)

    res_with_row = MagicMock()
    res_with_row.scalar_one_or_none.return_value = datetime(2026, 2, 4, 20, 0, tzinfo=UTC)

    mock_db.execute = AsyncMock(return_value=res_with_row)

    svc = TrackingService(mock_db, str(uid), session_factory=None)
    ok, d = _run(svc._should_perform_scenario_b_forced_reset(window_start, personal))
    assert ok is False
    assert d is None
    assert mock_db.execute.await_count == 1


def test_scenario_b_false_when_not_first_window_after_anchor():
    from api.services.tracking_service import TrackingService

    uid = uuid_mod.uuid4()
    user = MagicMock()
    user.last_morning_cycle_reset_local_date = None
    personal = MagicMock()
    personal.typical_wake_time = "07:00"

    ist = ZoneInfo("Asia/Kolkata")
    window_start = datetime(2026, 2, 5, 11, 30, tzinfo=ist).astimezone(UTC)

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=user)

    res_empty = MagicMock()
    res_empty.scalar_one_or_none.return_value = None
    res_prior = MagicMock()
    res_prior.scalar_one_or_none.return_value = uuid_mod.uuid4()

    mock_db.execute = AsyncMock(side_effect=[res_empty, res_prior])

    svc = TrackingService(mock_db, str(uid), session_factory=None)
    ok, d = _run(svc._should_perform_scenario_b_forced_reset(window_start, personal))
    assert ok is False
    assert d is None


def test_scenario_b_true_when_clean_first_touch_after_anchor():
    from api.services.tracking_service import TrackingService

    uid = uuid_mod.uuid4()
    user = MagicMock()
    user.last_morning_cycle_reset_local_date = None
    personal = MagicMock()
    personal.typical_wake_time = "07:00"

    ist = ZoneInfo("Asia/Kolkata")
    window_start = datetime(2026, 2, 5, 11, 30, tzinfo=ist).astimezone(UTC)

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=user)

    res_empty = MagicMock()
    res_empty.scalar_one_or_none.return_value = None

    mock_db.execute = AsyncMock(return_value=res_empty)

    svc = TrackingService(mock_db, str(uid), session_factory=None)
    ok, d = _run(svc._should_perform_scenario_b_forced_reset(window_start, personal))
    assert ok is True
    assert d == date(2026, 2, 5)
    assert mock_db.execute.await_count == 2


def test_scenario_b_true_when_first_wear_is_shortly_before_anchor():
    from api.services.tracking_service import TrackingService

    uid = uuid_mod.uuid4()
    user = MagicMock()
    user.last_morning_cycle_reset_local_date = None
    personal = MagicMock()
    personal.typical_wake_time = "07:00"

    ist = ZoneInfo("Asia/Kolkata")
    window_start = datetime(2026, 2, 5, 7, 5, tzinfo=ist).astimezone(UTC)
    pre_anchor_first_wear = datetime(2026, 2, 5, 6, 0, tzinfo=ist).astimezone(UTC)

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=user)

    res_pre_anchor = MagicMock()
    res_pre_anchor.scalar_one_or_none.return_value = pre_anchor_first_wear
    res_post_anchor_empty = MagicMock()
    res_post_anchor_empty.scalar_one_or_none.return_value = None

    mock_db.execute = AsyncMock(side_effect=[res_pre_anchor, res_post_anchor_empty])

    svc = TrackingService(mock_db, str(uid), session_factory=None)
    ok, d = _run(svc._should_perform_scenario_b_forced_reset(window_start, personal))
    assert ok is True
    assert d == date(2026, 2, 5)


def test_scenario_b_false_when_pre_anchor_wear_started_too_early():
    from api.services.tracking_service import TrackingService

    uid = uuid_mod.uuid4()
    user = MagicMock()
    user.last_morning_cycle_reset_local_date = None
    personal = MagicMock()
    personal.typical_wake_time = "07:00"

    ist = ZoneInfo("Asia/Kolkata")
    window_start = datetime(2026, 2, 5, 7, 5, tzinfo=ist).astimezone(UTC)
    overnight_first_wear = datetime(2026, 2, 5, 1, 30, tzinfo=ist).astimezone(UTC)

    mock_db = AsyncMock()
    mock_db.get = AsyncMock(return_value=user)

    res_pre_anchor = MagicMock()
    res_pre_anchor.scalar_one_or_none.return_value = overnight_first_wear
    mock_db.execute = AsyncMock(return_value=res_pre_anchor)

    svc = TrackingService(mock_db, str(uid), session_factory=None)
    ok, d = _run(svc._should_perform_scenario_b_forced_reset(window_start, personal))
    assert ok is False
    assert d is None
    assert mock_db.execute.await_count == 1


def test_nap_gate_constants_unchanged():
    from api.services.tracking_service import MIN_SLEEP_MINUTES_FOR_MORNING_RESET

    assert MIN_SLEEP_MINUTES_FOR_MORNING_RESET == 90.0
