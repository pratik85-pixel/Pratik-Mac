"""
Phase 3B — Single source for product calendar semantics.

All user-facing "today", recap "yesterday", and matching keys for DailyPlan /
DailyStressSummary use the same timezone: ``CONFIG.tracking.STRESS_STATE_TIMEZONE``
(currently Asia/Kolkata). Call sites must not hardcode ``ZoneInfo("Asia/Kolkata")``.

Row storage (summary_date / plan_date) remains the existing contract: local
calendar Y-M-D encoded as ``datetime(..., tzinfo=UTC)`` at 00:00 — see
``TrackingService._materialise_daily_score``. For **querying** a local day by
wall-clock span, use ``utc_instant_bounds_for_local_calendar_date``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from config import CONFIG


def product_calendar_timezone() -> ZoneInfo:
    return ZoneInfo(CONFIG.tracking.STRESS_STATE_TIMEZONE)


def local_today(now_utc: Optional[datetime] = None) -> date:
    """Calendar 'today' in the product timezone (plan, home, materialised day keys)."""
    if now_utc is None:
        now_utc = datetime.now(UTC)
    elif now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=UTC)
    return now_utc.astimezone(product_calendar_timezone()).date()


def recap_yesterday_local_date(now_utc: Optional[datetime] = None) -> date:
    """IST-style 'yesterday' for morning recap strict row (same as local_today - 1 day)."""
    return local_today(now_utc) - timedelta(days=1)


def utc_instant_bounds_for_local_calendar_date(d: date) -> tuple[datetime, datetime]:
    """Inclusive-exclusive UTC [start, end) for the local calendar day *d* in product TZ."""
    tz = product_calendar_timezone()
    local_start = datetime(d.year, d.month, d.day, tzinfo=tz)
    local_end = local_start + timedelta(days=1)
    return local_start.astimezone(UTC), local_end.astimezone(UTC)
