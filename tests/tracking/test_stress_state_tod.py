"""Time-of-day median helper (Phase 7)."""

from datetime import UTC, datetime, timedelta

from tracking.background_processor import BackgroundWindowResult
from tracking.stress_state import median_rmssd_same_weekday_hour


def _w(start: datetime, rmssd: float) -> BackgroundWindowResult:
    end = start + timedelta(minutes=5)
    return BackgroundWindowResult(
        user_id="u1",
        window_start=start,
        window_end=end,
        context="background",
        rmssd_ms=rmssd,
        hr_bpm=60.0,
        lf_hf=None,
        confidence=0.9,
        acc_mean=None,
        gyro_mean=None,
        n_beats=40,
        artifact_rate=0.0,
        is_valid=False,
    )


def test_median_tod_requires_min_samples():
    now = datetime(2026, 3, 25, 14, 30, tzinfo=UTC)
    wins = [_w(now - timedelta(days=7 * i), 40.0 + i) for i in range(3)]
    assert (
        median_rmssd_same_weekday_hour(wins, now, "UTC", min_samples=8) is None
    )


def test_median_tod_matches_weekday_hour():
    now = datetime(2026, 3, 25, 14, 30, tzinfo=UTC)  # Wed 14:xx UTC
    wins = []
    for i in range(10):
        t = datetime(2026, 3, 18, 14, i * 5, tzinfo=UTC) + timedelta(weeks=i // 5)
        wins.append(_w(t, 30.0 + float(i)))
    med = median_rmssd_same_weekday_hour(wins, now, "UTC", min_samples=8)
    assert med is not None
    assert 30.0 <= med <= 40.0
