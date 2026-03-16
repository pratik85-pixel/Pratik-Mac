"""
tests/model/test_calibration_filter.py

Unit tests for model/calibration_filter.py

Run with:
    pytest tests/model/test_calibration_filter.py -v
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

import pytest

from model.calibration_filter import (
    filter_calibration_windows,
    FilterResult,
    _POPULATION_CEILING,
    _SETTLING_MINUTES,
    _SPIKE_MULTIPLIER,
)


# ── Minimal stub that mimics BackgroundWindowResult ───────────────────────────

@dataclass
class _W:
    window_start: datetime
    rmssd_ms: float | None
    context: str = "background"
    is_valid: bool = True


def _ts(offset_minutes: float) -> datetime:
    """Return a UTC datetime `offset_minutes` after an arbitrary base time."""
    base = datetime(2026, 3, 16, 7, 0, 0, tzinfo=timezone.utc)
    return base + timedelta(minutes=offset_minutes)


def _make_windows(
    rmssd_values: list[float],
    start_offset_minutes: float = 0.0,
    spacing_minutes: float = 5.0,
) -> list[_W]:
    """Build a list of _W objects spaced `spacing_minutes` apart."""
    return [
        _W(
            window_start=_ts(start_offset_minutes + i * spacing_minutes),
            rmssd_ms=v,
        )
        for i, v in enumerate(rmssd_values)
    ]


# ── Test: empty input ─────────────────────────────────────────────────────────

def test_empty_input():
    result = filter_calibration_windows([])
    assert result.clean_windows == []
    assert result.windows_total == 0
    assert result.rejected_count == 0
    assert result.confidence == 0.0


# ── Test: Pass 1 — settling discard ──────────────────────────────────────────

def test_settling_window_rejection():
    """Windows within first 30 min of first window_start are discarded."""
    # 12 windows at 5-min spacing = 55 minutes of data (0 to 55)
    # First 6 windows (0–25 min) fall within settling period; 7th onwards pass.
    windows = _make_windows([35.0] * 12, start_offset_minutes=0.0)
    result = filter_calibration_windows(windows)

    # First window at 0 min → settle_cutoff = 30 min
    # Windows at 0, 5, 10, 15, 20, 25 min → 6 rejected
    assert result.windows_total == 12
    assert result.rejected_count >= 6
    # Clean windows all have window_start >= 30 min from the first
    for w in result.clean_windows:
        assert w.window_start >= _ts(_SETTLING_MINUTES)


def test_all_windows_in_settling_period():
    """If all windows fall in the settling period, confidence == 0."""
    windows = _make_windows([35.0] * 4, start_offset_minutes=0.0, spacing_minutes=5.0)
    # 4 windows at 0, 5, 10, 15 min — all within 30-min settle
    result = filter_calibration_windows(windows)
    assert result.clean_windows == []
    assert result.confidence == 0.0


# ── Test: Pass 2 — temporal spike gate ───────────────────────────────────────

def test_spike_gate_rejects_outlier():
    """A 150ms window surrounded by 30ms windows is rejected as a spike."""
    # Build 13 windows at ~30ms; inject spike at position 6
    values = [30.0] * 13
    values[6] = 150.0   # this is 5× the surrounding median → spike

    # Start well after settling period so Pass 1 doesn't interfere
    windows = _make_windows(values, start_offset_minutes=60.0)
    result = filter_calibration_windows(windows)

    # Spike window should be rejected
    assert result.rejected_count >= 1
    rmssd_clean = [w.rmssd_ms for w in result.clean_windows]
    assert 150.0 not in rmssd_clean


def test_spike_gate_passes_elevated_but_proportionate():
    """A moderately elevated window that is < 2.5× median is NOT rejected."""
    # All windows at 40ms except one at 80ms (2× median — under 2.5× threshold)
    values = [40.0] * 13
    values[6] = 80.0

    windows = _make_windows(values, start_offset_minutes=60.0)
    result = filter_calibration_windows(windows)

    rmssd_clean = [w.rmssd_ms for w in result.clean_windows]
    assert 80.0 in rmssd_clean


# ── Test: Pass 3 — population ceiling gate ───────────────────────────────────

def test_population_ceiling_gate():
    """Windows above 110ms are rejected unconditionally."""
    values = [35.0] * 10 + [_POPULATION_CEILING + 1.0]  # last one over cap

    windows = _make_windows(values, start_offset_minutes=60.0)
    result = filter_calibration_windows(windows)

    rmssd_clean = [w.rmssd_ms for w in result.clean_windows]
    assert all(v <= _POPULATION_CEILING for v in rmssd_clean)
    assert result.rejected_count >= 1


def test_population_ceiling_boundary_is_inclusive():
    """Exactly 110ms is accepted (gate is <= 110, not < 110)."""
    # Surrounding values must be >= 44ms so 110 <= 2.5×44=110 — use 50ms to be safe
    values = [50.0] * 10 + [_POPULATION_CEILING]

    windows = _make_windows(values, start_offset_minutes=60.0)
    result = filter_calibration_windows(windows)

    rmssd_clean = [w.rmssd_ms for w in result.clean_windows]
    assert _POPULATION_CEILING in rmssd_clean


# ── Test: clean path ──────────────────────────────────────────────────────────

def test_clean_path_no_artifacts():
    """No spike or ceiling violations — only settling discards occur (always expected).

    20 windows at 40ms: first 6 are settle-rejected (30-min settle window),
    remaining 14 pass all three artifact gates.
    """
    values = [40.0] * 20
    windows = _make_windows(values, start_offset_minutes=0.0)
    result = filter_calibration_windows(windows)

    # 6 settling windows rejected, 14 clean
    assert len(result.clean_windows) == 14
    # Every clean window passes the ceiling gate
    for w in result.clean_windows:
        assert w.rmssd_ms <= _POPULATION_CEILING
    # High confidence despite settling (rejection_rate=0.3 at boundary)
    assert result.confidence >= 0.85


# ── Test: confidence degrades with high rejection rate ────────────────────────

def test_confidence_degrades_above_threshold():
    """Rejection rate > 20% triggers confidence penalty."""
    # 10 valid windows and 5 windows above cap → 5/15 ≈ 33% rejection
    values = [40.0] * 10 + [120.0] * 5

    windows = _make_windows(values, start_offset_minutes=60.0)
    result = filter_calibration_windows(windows)

    assert result.rejection_rate > 0.20
    assert result.confidence < 1.0


# ── Test: None rmssd passes through without error ────────────────────────────

def test_none_rmssd_handled_gracefully():
    """Windows with rmssd_ms=None are passed through (not counted as spikes)."""
    windows = [
        _W(window_start=_ts(60.0 + i * 5), rmssd_ms=None if i == 3 else 35.0)
        for i in range(10)
    ]
    result = filter_calibration_windows(windows)
    # Should not raise; None windows pass through
    assert result.windows_total == 10
