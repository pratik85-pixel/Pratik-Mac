"""
tracking/stress_state.py

Point-in-time stress state + short trend for Home UX (Phase 2–3 API).

Uses log-space distance between RMSSD and personal morning reference (aligned with
daily_summarizer), smoothed with EMA over recent 5-min background windows.
Zones are personal-percentile-based when enough history exists; otherwise fixed
cutpoints on the 0–1 stress index.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Optional, Sequence
from zoneinfo import ZoneInfo

from tracking.background_processor import BackgroundWindowResult


# API zone ids (client maps to Calm / Steady / Activated / Depleted)
ZONE_CALM = "calm"
ZONE_STEADY = "steady"
ZONE_ACTIVATED = "activated"
ZONE_DEPLETED = "depleted"

TREND_EASING = "easing"
TREND_STABLE = "stable"
TREND_BUILDING = "building"
TREND_UNCLEAR = "unclear"

CONF_HIGH = "high"
CONF_MEDIUM = "medium"
CONF_LOW = "low"


@dataclass(frozen=True)
class StressStateResult:
    stress_now_zone: Optional[str]
    stress_now_index: Optional[float]
    stress_now_percent: Optional[float]
    trend: str
    confidence: str
    reference_type: str
    as_of: Optional[str]
    rmssd_smoothed_ms: Optional[float]
    # Transparency for clients that show “vs your history”
    zone_cut_index_low: Optional[float] = None   # below → calm
    zone_cut_index_mid: Optional[float] = None   # below → steady
    zone_cut_index_high: Optional[float] = None  # below → activated; else depleted
    morning_reference_ms: Optional[float] = None
    time_of_day_reference_ms: Optional[float] = None
    cohort_enabled: bool = False
    cohort_band: Optional[str] = None
    cohort_disclaimer: str = ""


def _clamp_rmssd(
    rmssd: float,
    floor_ms: Optional[float],
    ceiling_ms: Optional[float],
) -> float:
    x = rmssd
    if ceiling_ms is not None:
        x = min(x, ceiling_ms)
    if floor_ms is not None:
        x = max(x, floor_ms)
    return x


def stress_index_from_rmssd(
    rmssd_ms: float,
    personal_floor: float,
    personal_ref: float,
    personal_ceiling: Optional[float] = None,
) -> Optional[float]:
    """
    Map RMSSD to [0, 1] stress index: 0 = at/above reference (calm end),
    1 = at/below floor (max stress in personal range).
    """
    if rmssd_ms <= 0 or personal_ref <= 0:
        return None
    eff = _clamp_rmssd(rmssd_ms, personal_floor, personal_ceiling)
    if eff >= personal_ref:
        return 0.0
    lo = max(personal_floor, 1e-6)
    if personal_ref <= lo:
        return None
    if eff <= lo:
        return 1.0
    num = math.log(personal_ref) - math.log(eff)
    den = math.log(personal_ref) - math.log(lo)
    if den <= 0:
        return None
    return max(0.0, min(1.0, num / den))


def _ema_series(values: Sequence[float], alpha: float) -> list[float]:
    if not values:
        return []
    out: list[float] = []
    s = values[0]
    out.append(s)
    for x in values[1:]:
        s = alpha * x + (1.0 - alpha) * s
        out.append(s)
    return out


def _percentile_nearest(sorted_vals: list[float], p: float) -> float:
    """p in [0, 1]."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * p
    f = int(math.floor(k))
    c = int(math.ceil(k))
    if f == c:
        return sorted_vals[f]
    d0 = sorted_vals[f] * (c - k)
    d1 = sorted_vals[c] * (k - f)
    return d0 + d1


def _history_indices(
    windows: Sequence[BackgroundWindowResult],
    personal_floor: float,
    personal_ref: float,
    personal_ceiling: Optional[float],
) -> list[float]:
    idx: list[float] = []
    for w in windows:
        if not w.is_valid or w.context != "background" or w.rmssd_ms is None:
            continue
        v = stress_index_from_rmssd(
            w.rmssd_ms, personal_floor, personal_ref, personal_ceiling
        )
        if v is not None:
            idx.append(v)
    return idx


def _zone_from_index(
    index: float,
    c1: float,
    c2: float,
    c3: float,
) -> str:
    if index < c1:
        return ZONE_CALM
    if index < c2:
        return ZONE_STEADY
    if index < c3:
        return ZONE_ACTIVATED
    return ZONE_DEPLETED


def _default_cutpoints() -> tuple[float, float, float]:
    """Fixed cutpoints on stress index when history is thin."""
    return (0.25, 0.50, 0.75)


def median_rmssd_same_weekday_hour(
    windows: Sequence[BackgroundWindowResult],
    now: datetime,
    tz_name: str,
    min_samples: int,
) -> Optional[float]:
    """
    Median RMSSD for valid background windows whose local end time matches
    today's weekday and hour (for time-of-day reference).
    """
    tz = ZoneInfo(tz_name)
    now_utc = now.astimezone(UTC) if now.tzinfo else now.replace(tzinfo=UTC)
    now_local = now_utc.astimezone(tz)
    dow, hr = now_local.weekday(), now_local.hour
    vals: list[float] = []
    for w in windows:
        if not w.is_valid or w.context != "background" or w.rmssd_ms is None:
            continue
        le = w.window_end.astimezone(tz)
        if le.weekday() == dow and le.hour == hr:
            vals.append(float(w.rmssd_ms))
    if len(vals) < min_samples:
        return None
    vals.sort()
    n = len(vals)
    mid = n // 2
    if n % 2:
        return vals[mid]
    return (vals[mid - 1] + vals[mid]) / 2.0


def compute_stress_state(
    *,
    now: datetime,
    windows_history: Sequence[BackgroundWindowResult],
    personal_floor: float,
    personal_ref_morning: float,
    index_reference_ms: float,
    reference_type: str,
    personal_ceiling: Optional[float],
    ema_alpha: float,
    recent_span_hours: float,
    trend_lookback_minutes: int,
    trend_delta_threshold: float,
    min_history_for_percentiles: int,
    time_of_day_reference_ms: Optional[float] = None,
    cohort_enabled: bool = False,
    cohort_band: Optional[str] = None,
    cohort_disclaimer: str = "",
) -> StressStateResult:
    """
    windows_history: valid background windows, oldest first, typically last 28d.

    Zone cutpoints use history scored vs **morning** ref; live index + trend use
    ``index_reference_ms`` (morning or blended time-of-day).
    """
    now = now.astimezone(UTC) if now.tzinfo else now.replace(tzinfo=UTC)
    recent_cutoff = now - timedelta(hours=recent_span_hours)
    recent = [
        w
        for w in windows_history
        if w.is_valid
        and w.context == "background"
        and w.rmssd_ms is not None
        and w.window_end >= recent_cutoff
    ]
    recent.sort(key=lambda w: w.window_end)

    hist_idx = _history_indices(
        windows_history, personal_floor, personal_ref_morning, personal_ceiling
    )
    if len(hist_idx) >= min_history_for_percentiles:
        hist_idx.sort()
        c1 = _percentile_nearest(hist_idx, 0.40)
        c2 = _percentile_nearest(hist_idx, 0.65)
        c3 = _percentile_nearest(hist_idx, 0.85)
        # Degenerate history (e.g. all same index) collapses cutpoints — use defaults
        if c3 - c1 < 1e-5 or c2 <= c1 or c3 <= c2:
            cut_low, cut_mid, cut_high = _default_cutpoints()
        else:
            cut_low, cut_mid, cut_high = c1, c2, c3
    else:
        cut_low, cut_mid, cut_high = _default_cutpoints()

    if not recent:
        return StressStateResult(
            stress_now_zone=None,
            stress_now_index=None,
            stress_now_percent=None,
            trend=TREND_UNCLEAR,
            confidence=CONF_LOW,
            reference_type=reference_type,
            as_of=None,
            rmssd_smoothed_ms=None,
            zone_cut_index_low=cut_low,
            zone_cut_index_mid=cut_mid,
            zone_cut_index_high=cut_high,
            morning_reference_ms=round(personal_ref_morning, 2),
            time_of_day_reference_ms=(
                round(time_of_day_reference_ms, 2)
                if time_of_day_reference_ms is not None
                else None
            ),
            cohort_enabled=cohort_enabled,
            cohort_band=cohort_band,
            cohort_disclaimer=cohort_disclaimer,
        )

    rmssd_seq = [float(w.rmssd_ms) for w in recent if w.rmssd_ms is not None]
    smoothed_rmssd_list = _ema_series(rmssd_seq, ema_alpha)
    smoothed_rmssd = smoothed_rmssd_list[-1]
    last_window = recent[-1]
    as_of = last_window.window_end.astimezone(UTC).isoformat()

    idx_now = stress_index_from_rmssd(
        smoothed_rmssd, personal_floor, index_reference_ms, personal_ceiling
    )
    zone = (
        _zone_from_index(idx_now, cut_low, cut_mid, cut_high)
        if idx_now is not None
        else None
    )
    pct = round(idx_now * 100.0, 1) if idx_now is not None else None

    # Trend: compare EMA at end vs EMA at ~lookback minutes ago
    trend_cut = now - timedelta(minutes=trend_lookback_minutes)
    past_rmssd: list[float] = []
    for w in recent:
        if w.window_end <= trend_cut:
            past_rmssd.append(float(w.rmssd_ms))
    trend_label = TREND_UNCLEAR
    if past_rmssd:
        smoothed_past_list = _ema_series(past_rmssd, ema_alpha)
        smoothed_past = smoothed_past_list[-1]
        idx_past = stress_index_from_rmssd(
            smoothed_past, personal_floor, index_reference_ms, personal_ceiling
        )
        if idx_now is not None and idx_past is not None:
            delta = idx_now - idx_past
            if delta > trend_delta_threshold:
                trend_label = TREND_BUILDING
            elif delta < -trend_delta_threshold:
                trend_label = TREND_EASING
            else:
                trend_label = TREND_STABLE
    elif len(recent) >= 2 and idx_now is not None:
        # Short history: compare first vs last raw in window
        first = stress_index_from_rmssd(
            float(recent[0].rmssd_ms),
            personal_floor,
            index_reference_ms,
            personal_ceiling,
        )
        if first is not None:
            delta = idx_now - first
            if delta > trend_delta_threshold:
                trend_label = TREND_BUILDING
            elif delta < -trend_delta_threshold:
                trend_label = TREND_EASING
            else:
                trend_label = TREND_STABLE

    # Confidence from recency + density
    confidence = CONF_LOW
    if len(recent) >= 3:
        gaps = []
        for i in range(1, len(recent)):
            g = (recent[i].window_start - recent[i - 1].window_end).total_seconds() / 60.0
            gaps.append(g)
        max_gap = max(gaps) if gaps else 0.0
        last_age_min = (now - last_window.window_end).total_seconds() / 60.0
        if max_gap <= 25 and last_age_min <= 20:
            confidence = CONF_HIGH
        elif last_age_min <= 45:
            confidence = CONF_MEDIUM
    elif len(recent) >= 1:
        last_age_min = (now - last_window.window_end).total_seconds() / 60.0
        confidence = CONF_MEDIUM if last_age_min <= 45 else CONF_LOW

    return StressStateResult(
        stress_now_zone=zone,
        stress_now_index=round(idx_now, 4) if idx_now is not None else None,
        stress_now_percent=pct,
        trend=trend_label,
        confidence=confidence,
        reference_type=reference_type,
        as_of=as_of,
        rmssd_smoothed_ms=round(smoothed_rmssd, 2),
        zone_cut_index_low=round(cut_low, 4),
        zone_cut_index_mid=round(cut_mid, 4),
        zone_cut_index_high=round(cut_high, 4),
        morning_reference_ms=round(personal_ref_morning, 2),
        time_of_day_reference_ms=(
            round(time_of_day_reference_ms, 2)
            if time_of_day_reference_ms is not None
            else None
        ),
        cohort_enabled=cohort_enabled,
        cohort_band=cohort_band,
        cohort_disclaimer=cohort_disclaimer,
    )
