"""Phase 3B — product calendar helpers (deterministic)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tracking.cycle_boundaries import (
    local_today,
    recap_yesterday_local_date,
    utc_instant_bounds_for_local_calendar_date,
)


def test_local_today_fixed_utc_instant():
    # 2026-03-30 10:00 UTC → 15:30 IST same calendar day
    d = local_today(datetime(2026, 3, 30, 10, 0, 0, tzinfo=UTC))
    assert d.year == 2026
    assert d.month == 3
    assert d.day == 30


def test_local_today_crosses_date_boundary_utc():
    # 2026-03-29 18:30 UTC → 00:00 IST Mar 30
    d = local_today(datetime(2026, 3, 29, 18, 30, 0, tzinfo=UTC))
    assert d == datetime(2026, 3, 30).date()


def test_recap_yesterday_relative_to_local_today():
    d = recap_yesterday_local_date(datetime(2026, 3, 30, 10, 0, 0, tzinfo=UTC))
    assert d == datetime(2026, 3, 29).date()


def test_utc_bounds_span_real_ist_midnight():
    from datetime import date

    start, end = utc_instant_bounds_for_local_calendar_date(date(2026, 3, 30))
    assert start == datetime(2026, 3, 29, 18, 30, 0, tzinfo=UTC)
    assert end == datetime(2026, 3, 30, 18, 30, 0, tzinfo=UTC)
    assert (end - start).total_seconds() == 86400


@pytest.mark.parametrize(
    ("readiness", "day"),
    [
        (90.0, "green"),
        (76.0, "green"),
        (75.0, "yellow"),
        (60.0, "yellow"),
        (50.0, "yellow"),
        (49.0, "relaxed"),
        (25.0, "relaxed"),
        (24.9, "red"),
        (24.0, "red"),
        (0.0, "red"),
    ],
)
def test_day_type_from_readiness_mapping(readiness: float, day: str) -> None:
    from tracking.plan_readiness_contract import day_type_from_readiness

    assert day_type_from_readiness(readiness) == day


def test_compute_composite_readiness_formula() -> None:
    from tracking.plan_readiness_contract import compute_composite_readiness

    # v2: 0.45*sleep + 0.30*waking + 0.25*(10-stress)*10
    # 0.45*70 + 0.30*80 + 0.25*5*10 = 31.5 + 24 + 12.5 = 68.0
    r = compute_composite_readiness(80.0, 70.0, 5.0)
    assert r == 68.0

    assert compute_composite_readiness(100.0, 100.0, 0.0) == 100.0
    assert compute_composite_readiness(0.0, 0.0, 10.0) == 0.0
