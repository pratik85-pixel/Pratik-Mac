"""
tests/coach/test_band_coverage.py

Unit tests for `coach.input_builder._coverage_label_from_hours` and
`coach.input_builder._compute_band_coverage` — the deterministic wear-hours
context that feeds the coach's DATA_COVERAGE block.

No real DB required: the AsyncSession is mocked to return pre-seeded
`BandWearSession`-like rows.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from coach.input_builder import (
    _compute_band_coverage,
    _coverage_label_from_hours,
)
from tracking.cycle_boundaries import (
    recap_yesterday_local_date,
    utc_instant_bounds_for_local_calendar_date,
)


# ── Label bucketing ────────────────────────────────────────────────────────────

def test_coverage_label_none_and_zero() -> None:
    assert _coverage_label_from_hours(None) is None
    assert _coverage_label_from_hours(0) == "none"


def test_coverage_label_buckets() -> None:
    assert _coverage_label_from_hours(1.0) == "low"
    assert _coverage_label_from_hours(7.99) == "low"
    assert _coverage_label_from_hours(8.0) == "partial"
    assert _coverage_label_from_hours(15.9) == "partial"
    assert _coverage_label_from_hours(16.0) == "full"
    assert _coverage_label_from_hours(24.0) == "full"


# ── Wear-hours computation ─────────────────────────────────────────────────────

def _mock_session_with_rows(rows: list[object]) -> AsyncMock:
    """Return an AsyncMock that yields the given rows via execute().scalars().all()."""
    db = AsyncMock()
    scalar_result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = rows
    scalar_result.scalars.return_value = scalars
    db.execute.return_value = scalar_result
    return db


def _session(started_at: datetime, ended_at: datetime | None, has_sleep_data: bool = False):
    return SimpleNamespace(
        started_at=started_at,
        ended_at=ended_at,
        has_sleep_data=has_sleep_data,
    )


def test_compute_band_coverage_full_day_yesterday() -> None:
    """A single session covering all of yesterday should produce ~24 hours + full label."""
    now_utc = datetime(2026, 4, 22, 10, 0, tzinfo=UTC)
    y_local = recap_yesterday_local_date(now_utc)
    y_start, y_end = utc_instant_bounds_for_local_calendar_date(y_local)

    rows = [_session(y_start, y_end, has_sleep_data=True)]
    db = _mock_session_with_rows(rows)

    result = asyncio.run(
        _compute_band_coverage(db, uuid.uuid4(), now_utc=now_utc, days=7)
    )

    assert result["yesterday_date"] == y_local.isoformat()
    assert result["yesterday_wear_hours"] == 24.0
    assert result["yesterday_coverage_label"] == "full"
    assert result["has_sleep_data_yesterday"] is True
    assert isinstance(result["wear_hours_last7"], list)
    assert len(result["wear_hours_last7"]) == 7
    # The last slot (yesterday) should be 24h; earlier slots should be 0h.
    assert result["wear_hours_last7"][-1] == 24.0
    assert all(h == 0.0 for h in result["wear_hours_last7"][:-1])


def test_compute_band_coverage_partial_day_yesterday() -> None:
    """A 6-hour session in yesterday's local day should bucket as 'low'."""
    now_utc = datetime(2026, 4, 22, 10, 0, tzinfo=UTC)
    y_local = recap_yesterday_local_date(now_utc)
    y_start, y_end = utc_instant_bounds_for_local_calendar_date(y_local)

    session_start = y_start + timedelta(hours=9)
    session_end = session_start + timedelta(hours=6)

    rows = [_session(session_start, session_end, has_sleep_data=False)]
    db = _mock_session_with_rows(rows)

    result = asyncio.run(
        _compute_band_coverage(db, uuid.uuid4(), now_utc=now_utc)
    )

    assert result["yesterday_wear_hours"] == 6.0
    assert result["yesterday_coverage_label"] == "low"
    assert result["has_sleep_data_yesterday"] is False


def test_compute_band_coverage_no_wear_yesterday() -> None:
    """No sessions at all → zero hours and 'none' label."""
    now_utc = datetime(2026, 4, 22, 10, 0, tzinfo=UTC)

    db = _mock_session_with_rows([])

    result = asyncio.run(
        _compute_band_coverage(db, uuid.uuid4(), now_utc=now_utc)
    )

    assert result["yesterday_wear_hours"] == 0.0
    assert result["yesterday_coverage_label"] == "none"
    assert result["has_sleep_data_yesterday"] is False


def test_compute_band_coverage_clips_session_straddling_midnight() -> None:
    """
    A session that starts before yesterday and ends during yesterday should
    only contribute the overlap, not the full duration.
    """
    now_utc = datetime(2026, 4, 22, 10, 0, tzinfo=UTC)
    y_local = recap_yesterday_local_date(now_utc)
    y_start, _ = utc_instant_bounds_for_local_calendar_date(y_local)

    # Session: 5h before yesterday's local start, runs 3h into yesterday.
    started = y_start - timedelta(hours=5)
    ended = y_start + timedelta(hours=3)

    rows = [_session(started, ended)]
    db = _mock_session_with_rows(rows)

    result = asyncio.run(
        _compute_band_coverage(db, uuid.uuid4(), now_utc=now_utc)
    )

    assert result["yesterday_wear_hours"] == 3.0
    assert result["yesterday_coverage_label"] == "low"
