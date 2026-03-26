"""Unit tests for nap-safe morning wake window helper."""

from __future__ import annotations

from datetime import datetime

from zoneinfo import ZoneInfo

from api.services.tracking_service import (
    MIN_SLEEP_MINUTES_FOR_MORNING_RESET,
    transition_in_morning_wake_window,
)


def test_wake_window_7am_anchor_ist_default():
    tz = ZoneInfo("Asia/Kolkata")
    assert transition_in_morning_wake_window(
        datetime(2026, 2, 5, 7, 0, tzinfo=tz), None, "Asia/Kolkata"
    )
    assert transition_in_morning_wake_window(
        datetime(2026, 2, 5, 5, 0, tzinfo=tz), None, "Asia/Kolkata"
    )
    assert transition_in_morning_wake_window(
        datetime(2026, 2, 5, 11, 0, tzinfo=tz), None, "Asia/Kolkata"
    )
    assert not transition_in_morning_wake_window(
        datetime(2026, 2, 5, 4, 59, tzinfo=tz), None, "Asia/Kolkata"
    )
    assert not transition_in_morning_wake_window(
        datetime(2026, 2, 5, 11, 1, tzinfo=tz), None, "Asia/Kolkata"
    )
    assert not transition_in_morning_wake_window(
        datetime(2026, 2, 5, 15, 0, tzinfo=tz), None, "Asia/Kolkata"
    )


def test_wake_window_custom_typical_wake():
    tz = ZoneInfo("Asia/Kolkata")
    # Anchor 08:30 -> window 06:30–12:30
    assert transition_in_morning_wake_window(
        datetime(2026, 2, 5, 8, 30, tzinfo=tz), "08:30", "Asia/Kolkata"
    )
    assert transition_in_morning_wake_window(
        datetime(2026, 2, 5, 6, 30, tzinfo=tz), "08:30", "Asia/Kolkata"
    )
    assert not transition_in_morning_wake_window(
        datetime(2026, 2, 5, 6, 29, tzinfo=tz), "08:30", "Asia/Kolkata"
    )


def test_min_sleep_constant():
    assert MIN_SLEEP_MINUTES_FOR_MORNING_RESET == 90.0
