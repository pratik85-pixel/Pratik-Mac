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
    ("load", "readiness", "day"),
    [
        (0.0, 100.0, "green"),
        (0.34, 66.0, "green"),
        (0.35, 65.0, "yellow"),
        (0.64, 36.0, "yellow"),
        (0.65, 35.0, "red"),
        (1.0, 0.0, "red"),
        (1.5, 0.0, "red"),
    ],
)
def test_plan_readiness_contract_mapping(load: float, readiness: float, day: str) -> None:
    from tracking.plan_readiness_contract import (
        plan_day_type_from_load_score,
        plan_readiness_from_load_score,
    )

    assert plan_readiness_from_load_score(load) == readiness
    assert plan_day_type_from_load_score(load) == day
