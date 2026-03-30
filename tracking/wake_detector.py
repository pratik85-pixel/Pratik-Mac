"""
tracking/wake_detector.py

Determines waking and sleep boundaries for a given calendar day.

These boundaries define the stress accumulation window (wake → sleep) and
the recovery window (yesterday's morning read → today's morning read).

Two-tier detection — band data takes absolute precedence:

    Wake:
        Tier 1 (band worn): sleep → background context transition
        Tier 2 (no band):   historical typical_wake_time, then morning read,
                            then 07:00 IST hardcoded

    Sleep:
        Tier 1 (band worn): background → sleep context transition
        Tier 2 (no band):   last_background_window_ts + 30 min buffer,
                            then 22:00 IST hardcoded

When no band transitions exist, ``typical_sleep_time`` (with ``typical_wake_time``)
is used to place ``sleep_ts`` on the calendar day. Live ``background → sleep``
transitions still take precedence over historical typicals.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from config import CONFIG


@dataclass
class ContextTransition:
    """
    A single context switch event from the bridge stream.
    The bridge emits these when context changes: background → sleep, sleep → background, etc.
    """
    ts:           datetime
    from_context: str    # "background" | "sleep" | "session" | "morning_read"
    to_context:   str


@dataclass
class WakeSleepBoundary:
    """
    The determined wake and sleep boundaries for a single calendar day.
    Both are stored on DailyStressSummary.
    """
    user_id:                str
    day_date:               datetime          # date only (time component ignored)
    wake_ts:                datetime
    sleep_ts:               Optional[datetime]     # None if day not yet closed
    wake_detection_method:  str               # "sleep_transition" | "historical_pattern" | "morning_read_anchor"
    sleep_detection_method: Optional[str]     # same options + "last_background"
    waking_minutes:         Optional[float]   # sleep_ts - wake_ts in minutes (None if open)


def detect_wake_sleep_boundary(
    day_date: datetime,
    user_id: str,
    context_transitions: Optional[list[ContextTransition]] = None,
    typical_wake_time: Optional[str] = None,
    typical_sleep_time: Optional[str] = None,
    morning_read_ts: Optional[datetime] = None,
    last_background_window_ts: Optional[datetime] = None,
) -> WakeSleepBoundary:
    """
    Determine the wake and sleep boundaries for a day.

    Parameters
    ----------
    day_date : datetime
        The calendar day being analyzed. Time component is ignored.
    user_id : str
    context_transitions : list[ContextTransition], optional
        All bridge context transitions for the day (and preceding night).
        If None or empty, fallback chain is used.
    typical_wake_time : str, optional
        PersonalModel.typical_wake_time as "HH:MM" (rolling 14-day median).
    typical_sleep_time : str, optional
        PersonalModel.typical_sleep_time as "HH:MM".
    morning_read_ts : datetime, optional
        Timestamp of the morning physiological read (last-resort wake anchor).
    last_background_window_ts : datetime, optional
        Last background window timestamp of the prior day (sleep time fallback).

    Returns
    -------
    WakeSleepBoundary
    """
    cfg = CONFIG.tracking

    wake_ts: Optional[datetime] = None
    wake_method: str = "morning_read_anchor"
    sleep_ts: Optional[datetime] = None
    sleep_method: Optional[str] = None

    # ── Wake time detection ─────────────────────────────────────────────────

    # Tier 1 (band worn): sleep → background context transition
    if context_transitions:
        for t in sorted(context_transitions, key=lambda x: x.ts):
            if t.from_context == "sleep" and t.to_context == "background":
                if _is_same_date(t.ts, day_date):
                    wake_ts = t.ts
                    wake_method = "sleep_transition"
                    break

    # Tier 2 (no band): historical pattern → morning read → hardcoded
    if wake_ts is None:
        if typical_wake_time:
            wake_ts = _parse_time_on_date(typical_wake_time, day_date)
            wake_method = "historical_pattern"
        elif morning_read_ts is not None:
            wake_ts = morning_read_ts
            wake_method = "morning_read_anchor"
        else:
            # Absolute fallback: 07:00 IST = 01:30 UTC
            wake_ts = day_date.replace(hour=1, minute=30, second=0, microsecond=0)
            wake_method = "morning_read_anchor"

    # ── Sleep time detection ────────────────────────────────────────────────

    # Tier 1 (band worn): background → sleep context transition
    if context_transitions:
        for t in sorted(context_transitions, key=lambda x: x.ts):
            if t.from_context == "background" and t.to_context == "sleep":
                if t.ts > wake_ts:
                    max_awake = wake_ts + timedelta(hours=28)
                    if t.ts <= max_awake:
                        sleep_ts = t.ts
                        sleep_method = "sleep_transition"
                        break

    # Tier 2 (no band): typical sleep → last background + buffer → hardcoded
    if sleep_ts is None:
        if typical_sleep_time:
            sleep_ts = _parse_time_on_date(typical_sleep_time, day_date)
            if sleep_ts <= wake_ts:
                sleep_ts = sleep_ts + timedelta(days=1)
            sleep_method = "historical_pattern"
        elif last_background_window_ts is not None:
            sleep_ts = last_background_window_ts + timedelta(minutes=30)
            sleep_method = "last_background"
        else:
            # Absolute fallback: 22:00 IST = 16:30 UTC
            sleep_ts = day_date.replace(hour=16, minute=30, second=0, microsecond=0)
            if sleep_ts <= wake_ts:
                sleep_ts = sleep_ts + timedelta(days=1)
            sleep_method = "no_band_default"

    # Compute waking minutes
    waking_minutes: Optional[float] = None
    if sleep_ts is not None:
        waking_minutes = max(0.0, (sleep_ts - wake_ts).total_seconds() / 60.0)

    return WakeSleepBoundary(
        user_id=user_id,
        day_date=day_date,
        wake_ts=wake_ts,
        sleep_ts=sleep_ts,
        wake_detection_method=wake_method,
        sleep_detection_method=sleep_method,
        waking_minutes=waking_minutes,
    )


def compute_typical_wake_time(
    historical_boundaries: list[WakeSleepBoundary],
) -> Optional[str]:
    """
    Compute the rolling median wake time from the last N days of confirmed boundaries.
    Returns "HH:MM" string, or None if insufficient data.
    """
    cfg = CONFIG.tracking
    confirmed = [
        b for b in historical_boundaries
        if b.wake_detection_method == "sleep_transition"
    ]
    if len(confirmed) < 3:
        return None

    # Use last WAKE_HISTORY_DAYS worth of data
    confirmed = sorted(confirmed, key=lambda b: b.day_date)[-cfg.WAKE_HISTORY_DAYS:]

    # Convert to minutes-since-midnight, compute median
    minutes_list = [
        b.wake_ts.hour * 60 + b.wake_ts.minute
        for b in confirmed
    ]
    minutes_list.sort()
    n = len(minutes_list)
    median_minutes = (
        minutes_list[n // 2]
        if n % 2 == 1
        else (minutes_list[n // 2 - 1] + minutes_list[n // 2]) // 2
    )
    return f"{median_minutes // 60:02d}:{median_minutes % 60:02d}"


def compute_typical_sleep_time(
    historical_boundaries: list[WakeSleepBoundary],
) -> Optional[str]:
    """
    Compute the rolling median sleep time from confirmed boundaries.
    Returns "HH:MM" string, or None if insufficient data.
    """
    cfg = CONFIG.tracking
    confirmed = [
        b for b in historical_boundaries
        if b.sleep_detection_method == "sleep_transition"
        and b.sleep_ts is not None
    ]
    if len(confirmed) < 3:
        return None

    confirmed = sorted(confirmed, key=lambda b: b.day_date)[-cfg.WAKE_HISTORY_DAYS:]

    minutes_list = [
        b.sleep_ts.hour * 60 + b.sleep_ts.minute  # type: ignore[union-attr]
        for b in confirmed
    ]
    minutes_list.sort()
    n = len(minutes_list)
    median_minutes = (
        minutes_list[n // 2]
        if n % 2 == 1
        else (minutes_list[n // 2 - 1] + minutes_list[n // 2]) // 2
    )
    return f"{median_minutes // 60:02d}:{median_minutes % 60:02d}"


def _parse_time_on_date(time_str: str, date: datetime) -> datetime:
    """Parse "HH:MM" and return it as a datetime on the given date."""
    h, m = (int(x) for x in time_str.split(":"))
    return date.replace(hour=h, minute=m, second=0, microsecond=0)


def _is_same_date(ts: datetime, date: datetime) -> bool:
    """Check if ts falls on the same calendar date as date."""
    return ts.date() == date.date()
