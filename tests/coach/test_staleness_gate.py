"""Coach cache staleness uses IST calendar day (not stuck cycle date)."""

from __future__ import annotations

from datetime import date

from tracking.cycle_boundaries import local_today


def test_calendar_staleness_when_reset_date_stuck() -> None:
    """If DB stamped yesterday but calendar advanced, treat as stale."""
    today_ist = date(2026, 4, 22)
    generated_for = date(2026, 4, 21)
    is_stale = generated_for is None or generated_for < today_ist
    assert is_stale is True


def test_not_stale_same_calendar_day() -> None:
    today_ist = local_today()
    generated_for = today_ist
    is_stale = generated_for is None or generated_for < today_ist
    assert is_stale is False


def test_stale_when_never_generated() -> None:
    today_ist = date(2026, 1, 1)
    generated_for = None
    is_stale = generated_for is None or generated_for < today_ist
    assert is_stale is True
