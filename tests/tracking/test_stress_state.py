"""Unit tests for tracking/stress_state.py (Phase 2–3 stress now + trend)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tracking.background_processor import BackgroundWindowResult
from tracking.stress_state import (
    TREND_BUILDING,
    TREND_EASING,
    TREND_STABLE,
    ZONE_ACTIVATED,
    ZONE_CALM,
    compute_stress_state,
    stress_index_from_rmssd,
)


def _win(
    start: datetime,
    rmssd: float,
    *,
    valid: bool = True,
) -> BackgroundWindowResult:
    end = start + timedelta(minutes=5)
    w = BackgroundWindowResult(
        user_id="u1",
        window_start=start,
        window_end=end,
        context="background",
        rmssd_ms=rmssd,
        hr_bpm=60.0,
        lf_hf=None,
        confidence=0.9 if valid else 0.2,
        acc_mean=None,
        gyro_mean=None,
        n_beats=40,
        artifact_rate=0.0,
        is_valid=False,
    )
    return w


def test_stress_index_at_reference_is_zero():
    assert stress_index_from_rmssd(40.0, 18.0, 40.0, 90.0) == 0.0


def test_stress_index_below_reference_positive():
    idx = stress_index_from_rmssd(20.0, 18.0, 40.0, 90.0)
    assert idx is not None
    assert 0 < idx < 1


def test_stress_index_at_floor_is_one():
    idx = stress_index_from_rmssd(18.0, 18.0, 40.0, 90.0)
    assert idx == 1.0


def test_compute_stress_state_no_recent():
    now = datetime(2026, 3, 25, 12, 0, tzinfo=UTC)
    r = compute_stress_state(
        now=now,
        windows_history=[],
        personal_floor=20.0,
        personal_ref_morning=40.0,
        index_reference_ms=40.0,
        reference_type="morning_avg",
        personal_ceiling=80.0,
        ema_alpha=0.35,
        recent_span_hours=8.0,
        trend_lookback_minutes=90,
        trend_delta_threshold=0.06,
        min_history_for_percentiles=20,
    )
    assert r.stress_now_zone is None
    assert r.trend == "unclear"
    assert r.confidence == "low"


def test_compute_stress_state_high_rmssd_calm_zone():
    now = datetime(2026, 3, 25, 12, 0, tzinfo=UTC)
    wins = []
    t = now - timedelta(minutes=30)
    for i in range(6):
        wins.append(_win(t + timedelta(minutes=5 * i), 55.0))
    r = compute_stress_state(
        now=now,
        windows_history=wins,
        personal_floor=18.0,
        personal_ref_morning=35.0,
        index_reference_ms=35.0,
        reference_type="morning_avg",
        personal_ceiling=90.0,
        ema_alpha=0.5,
        recent_span_hours=8.0,
        trend_lookback_minutes=90,
        trend_delta_threshold=0.06,
        min_history_for_percentiles=5,
    )
    assert r.stress_now_zone == ZONE_CALM
    assert r.stress_now_index is not None
    assert r.stress_now_index < 0.15


def test_compute_stress_state_trend_building():
    now = datetime(2026, 3, 25, 14, 0, tzinfo=UTC)
    wins = []
    base = now - timedelta(hours=3)
    # Start calm RMSSD, end stressed — descending RMSSD
    vals = [50.0, 48.0, 45.0, 30.0, 22.0, 20.0, 19.0]
    for i, v in enumerate(vals):
        wins.append(_win(base + timedelta(minutes=5 * i), v))
    r = compute_stress_state(
        now=now,
        windows_history=wins,
        personal_floor=15.0,
        personal_ref_morning=45.0,
        index_reference_ms=45.0,
        reference_type="morning_avg",
        personal_ceiling=90.0,
        ema_alpha=0.45,
        recent_span_hours=8.0,
        trend_lookback_minutes=60,
        trend_delta_threshold=0.03,
        min_history_for_percentiles=5,
    )
    assert r.trend in (TREND_BUILDING, TREND_STABLE)
    assert r.stress_now_zone is not None


def test_compute_stress_state_trend_easing():
    now = datetime(2026, 3, 25, 14, 0, tzinfo=UTC)
    wins = []
    base = now - timedelta(hours=2)
    vals = [22.0, 24.0, 28.0, 35.0, 42.0, 48.0]
    for i, v in enumerate(vals):
        wins.append(_win(base + timedelta(minutes=5 * i), v))
    r = compute_stress_state(
        now=now,
        windows_history=wins,
        personal_floor=15.0,
        personal_ref_morning=45.0,
        index_reference_ms=45.0,
        reference_type="morning_avg",
        personal_ceiling=90.0,
        ema_alpha=0.4,
        recent_span_hours=8.0,
        trend_lookback_minutes=30,
        trend_delta_threshold=0.02,
        min_history_for_percentiles=5,
    )
    assert r.trend in (TREND_EASING, TREND_STABLE)
