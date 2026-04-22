"""
api/services/tracking_service.py

Orchestrates the all-day tracking pipeline.

Responsibilities
----------------
1. Ingest a new 5-min background window (PPI → BackgroundWindowResult → DB).
2. Re-run stress + recovery detection over today's windows when a new window arrives.
3. Close the day: finalize DailyStressSummary, update PersonalModel capacity metrics.
4. Serve pre-aggregated data for the API layer (no raw computation in routers).

Design
------
- All DB reads/writes use SQLAlchemy async sessions.
- Computation is delegated to tracking/ module; service only persists results.
- Intraday operation: called after every 5-min background window is stored.
- Day-close operation: called when sleep boundary is confirmed (or midnight).
- Thread-safety: single-threaded asyncio throughout.
"""

from __future__ import annotations

import logging
from time import perf_counter
from dataclasses import asdict, replace
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Optional, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from tracking.background_processor import BackgroundWindowResult, aggregate_background_window
from tracking.stress_detector import StressWindowResult, detect_stress_windows, compute_stress_contributions
from tracking.recovery_detector import RecoveryWindowResult, detect_recovery_windows, compute_recovery_contributions
from tracking.daily_summarizer import DailySummaryResult, compute_daily_summary
from tracking.cycle_boundaries import (
    local_today,
    recap_yesterday_local_date,
    utc_instant_bounds_for_local_calendar_date,
)
from tracking.locked_metrics_contract import contract_metadata_for_row
from tracking.plan_readiness_contract import compute_composite_readiness
from tracking.cohort_insight import build_cohort_insight
from tracking.stress_state import (
    StressStateResult,
    compute_stress_state,
    median_rmssd_same_weekday_hour,
)
from tracking.wake_detector import WakeSleepBoundary, ContextTransition, detect_wake_sleep_boundary

import numpy as np

from api.db import schema as db
from api.services.morning_bundle_orchestrator import MorningBundleOrchestrator
from api.utils import parse_uuid
from config import CONFIG

logger = logging.getLogger(__name__)


def _clamp_pct(v: Optional[float]) -> float:
    if v is None:
        return 0.0
    return max(0.0, min(100.0, float(v)))


def _parse_hhmm(value: Optional[str]) -> Optional[tuple[int, int]]:
    if not value:
        return None
    try:
        hh_s, mm_s = value.split(":", 1)
        hh = int(hh_s)
        mm = int(mm_s)
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return hh, mm
    except Exception:
        return None
    return None


# Nap-safe morning reset: typical_wake ± window; min sleep block; one reset per local day
MORNING_WAKE_WINDOW_PRE_HOURS = 2
MORNING_WAKE_WINDOW_POST_HOURS = 4
MIN_SLEEP_MINUTES_FOR_MORNING_RESET = 90.0

# Scenario B nuance: allow first wear shortly before anchor (e.g. 06:00 for 07:00 anchor)
# to still execute the morning reset at first post-anchor ingest.
SCENARIO_B_PRE_ANCHOR_FIRST_WEAR_GRACE_MINUTES = 180

# When stress/recovery windows are re-detected, start/end times shift slightly.
# Exact (started_at, ended_at) match fails; overlap carry preserves user tags.
_TAG_OVERLAP_MIN_FRACTION = 0.45


def _normalize_ts_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC, microsecond=0)
    return dt.astimezone(UTC).replace(microsecond=0)


def _overlap_interval_seconds(
    a0: datetime,
    a1: datetime,
    b0: datetime,
    b1: datetime,
) -> float:
    a0, a1 = _normalize_ts_utc(a0), _normalize_ts_utc(a1)
    b0, b1 = _normalize_ts_utc(b0), _normalize_ts_utc(b1)
    s = max(a0, b0)
    e = min(a1, b1)
    if e <= s:
        return 0.0
    return (e - s).total_seconds()


def _carry_user_tag_from_prior_intervals(
    *,
    started_at: datetime,
    ended_at: datetime,
    exact_key: tuple[datetime, datetime],
    exact_map: dict[tuple[datetime, datetime], tuple[str, str | None]],
    prior_intervals: list[tuple[datetime, datetime, str, str]],
    min_overlap_fraction: float = _TAG_OVERLAP_MIN_FRACTION,
) -> tuple[Optional[str], Optional[str]]:
    """
    Resolve user tag for a newly detected window: exact key first, else best overlap
    with any prior user-tagged interval (same calendar stress/recovery episode after recompute).
    """
    exact = exact_map.get(exact_key)
    if exact is not None:
        return exact[0], exact[1] or "user_confirmed"
    ns = _normalize_ts_utc(started_at)
    ne = _normalize_ts_utc(ended_at)
    dur_new = (ne - ns).total_seconds()
    if dur_new <= 0:
        return None, None
    best_tag: Optional[str] = None
    best_src: Optional[str] = None
    best_frac = 0.0
    for ps, pe, tag, src in prior_intervals:
        ps_u = _normalize_ts_utc(ps)
        pe_u = _normalize_ts_utc(pe)
        dur_p = (pe_u - ps_u).total_seconds()
        if dur_p <= 0:
            continue
        ov = _overlap_interval_seconds(ns, ne, ps_u, pe_u)
        if ov <= 0:
            continue
        denom = min(dur_new, dur_p)
        frac = ov / denom if denom > 0 else 0.0
        if frac >= min_overlap_fraction and frac > best_frac:
            best_frac = frac
            best_tag = tag
            best_src = src
    if best_tag is not None:
        return best_tag, best_src or "user_confirmed"
    return None, None


def anchor_utc_for_local_calendar_date(
    local_day: date,
    typical_wake_hhmm: Optional[str],
    tz_name: str,
) -> datetime:
    """
    Morning anchor instant in UTC for a given local calendar day
    (typical_wake_time or 07:00 in tz_name).
    """
    tz = ZoneInfo(tz_name)
    hhmm = _parse_hhmm(typical_wake_hhmm)
    anchor_h, anchor_m = hhmm if hhmm is not None else (7, 0)
    local_dt = datetime.combine(local_day, time(anchor_h, anchor_m), tzinfo=tz)
    return local_dt.astimezone(UTC)


def transition_in_morning_wake_window(
    transition_utc: datetime,
    typical_wake_hhmm: Optional[str],
    tz_name: str,
) -> bool:
    """
    True if transition local time falls in [anchor - 2h, anchor + 4h] on that calendar day,
    where anchor is typical_wake_time or 07:00 in tz_name.
    """
    local_tz = ZoneInfo(tz_name)
    t_local = transition_utc.astimezone(local_tz)
    d = t_local.date()
    hhmm = _parse_hhmm(typical_wake_hhmm)
    anchor_h, anchor_m = hhmm if hhmm is not None else (7, 0)
    anchor_local = datetime.combine(d, time(anchor_h, anchor_m), tzinfo=local_tz)
    win_start = anchor_local - timedelta(hours=MORNING_WAKE_WINDOW_PRE_HOURS)
    win_end = anchor_local + timedelta(hours=MORNING_WAKE_WINDOW_POST_HOURS)
    return win_start <= t_local <= win_end


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _to_db_background(r: BackgroundWindowResult) -> db.BackgroundWindow:
    return db.BackgroundWindow(
        user_id      = r.user_id,
        window_start = r.window_start,
        window_end   = r.window_end,
        context      = r.context,
        rmssd_ms     = r.rmssd_ms,
        hr_bpm       = r.hr_bpm,
        lf_hf        = r.lf_hf,
        confidence   = r.confidence,
        acc_mean     = r.acc_mean,
        gyro_mean    = r.gyro_mean,
        n_beats      = r.n_beats,
        artifact_rate = r.artifact_rate,
        is_valid     = r.is_valid,
    )


def _to_db_stress(r: StressWindowResult) -> db.StressWindow:
    return db.StressWindow(
        user_id      = r.user_id,
        started_at   = r.started_at,
        ended_at     = r.ended_at,
        duration_minutes = r.duration_minutes,
        rmssd_min_ms     = r.rmssd_min_ms,
        suppression_pct  = r.suppression_pct,
        stress_contribution_pct = r.stress_contribution_pct,
        suppression_area        = r.suppression_area,
        tag          = r.tag,
        tag_candidate = r.tag_candidate,
        tag_source   = r.tag_source,
        nudge_sent   = r.nudge_sent,
        nudge_responded = r.nudge_responded,
    )


def _to_db_recovery(r: RecoveryWindowResult) -> db.RecoveryWindow:
    return db.RecoveryWindow(
        user_id          = r.user_id,
        started_at       = r.started_at,
        ended_at         = r.ended_at,
        duration_minutes = r.duration_minutes,
        context          = r.context,
        rmssd_avg_ms     = r.rmssd_avg_ms,
        recovery_contribution_pct = r.recovery_contribution_pct,
        recovery_area    = r.recovery_area,
        tag              = r.tag,
        tag_source       = r.tag_source,
        zenflow_session_id = r.zenflow_session_id,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Queries
# ──────────────────────────────────────────────────────────────────────────────

async def _load_today_background(
    db_session: AsyncSession,
    user_id: str,
    day_start: datetime,
    day_end: datetime,
) -> list[BackgroundWindowResult]:
    """
    Load BackgroundWindow rows for a given day and reconstruct dataclass objects.
    """
    result = await db_session.execute(
        select(db.BackgroundWindow)
        .where(db.BackgroundWindow.user_id == user_id)
        .where(db.BackgroundWindow.window_start >= day_start)
        .where(db.BackgroundWindow.window_start < day_end)
        .order_by(db.BackgroundWindow.window_start)
    )
    rows = result.scalars().all()

    windows: list[BackgroundWindowResult] = []
    for row in rows:
        windows.append(BackgroundWindowResult(
            user_id      = str(row.user_id),
            window_start = row.window_start,
            window_end   = row.window_end,
            context      = row.context,
            rmssd_ms     = row.rmssd_ms,
            hr_bpm       = row.hr_bpm,
            lf_hf        = row.lf_hf,
            confidence   = row.confidence,
            acc_mean     = row.acc_mean,
            gyro_mean    = row.gyro_mean,
            n_beats      = row.n_beats,
            artifact_rate = row.artifact_rate,
            is_valid     = row.is_valid,
        ))
    return windows


async def _load_personal_model(
    db_session: AsyncSession, user_id: str
) -> Optional[db.PersonalModel]:
    result = await db_session.execute(
        select(db.PersonalModel)
        .where(db.PersonalModel.user_id == user_id)
        .order_by(db.PersonalModel.updated_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _load_existing_stress_windows(
    db_session: AsyncSession,
    user_id: str,
    day_start: datetime,
    day_end: datetime,
) -> list[db.StressWindow]:
    result = await db_session.execute(
        select(db.StressWindow)
        .where(db.StressWindow.user_id == user_id)
        .where(db.StressWindow.started_at >= day_start)
        .where(db.StressWindow.started_at < day_end)
    )
    return result.scalars().all()


async def _load_existing_recovery_windows(
    db_session: AsyncSession,
    user_id: str,
    day_start: datetime,
    day_end: datetime,
) -> list[db.RecoveryWindow]:
    result = await db_session.execute(
        select(db.RecoveryWindow)
        .where(db.RecoveryWindow.user_id == user_id)
        .where(db.RecoveryWindow.started_at >= day_start)
        .where(db.RecoveryWindow.started_at < day_end)
    )
    return result.scalars().all()


# ──────────────────────────────────────────────────────────────────────────────
# PersonalModel bootstrap (Phase 1 — unblocks detection pipeline on first wear)
# ──────────────────────────────────────────────────────────────────────────────

# Population-average seeds — now tiered by onboarding fitness level.
# exercise_frequency values come from users.onboarding JSON (set at onboarding).
_TIER_SEDENTARY = {"floor": 18.0, "ceiling": 45.0, "morning": 28.0}  # "rarely"
_TIER_MODERATE  = {"floor": 22.0, "ceiling": 65.0, "morning": 38.0}  # "1-3x/week"
_TIER_ATHLETIC  = {"floor": 35.0, "ceiling": 95.0, "morning": 55.0}  # "4+/week"
_EXERCISE_FREQ_TIERS: dict = {
    "rarely":    _TIER_SEDENTARY,
    "1-3x/week": _TIER_MODERATE,
    "4+/week":   _TIER_ATHLETIC,
}

_MIN_WINDOWS_FOR_REFINE = 3   # legacy constant kept for reference


def _seed_from_onboarding(onboarding: "Optional[dict]") -> "tuple[float, float, float]":
    """Return (floor_ms, ceiling_ms, morning_ms) from the user's fitness tier."""
    if onboarding is None:
        tier = _TIER_MODERATE
    else:
        freq = onboarding.get("exercise_frequency", "1-3x/week")
        tier = _EXERCISE_FREQ_TIERS.get(freq, _TIER_MODERATE)
    return tier["floor"], tier["ceiling"], tier["morning"]


def _seed_sleep_from_onboarding(onboarding: "Optional[dict]") -> "tuple[float, float]":
    """
    Return (sleep_avg_ms, sleep_ceiling_ms) population-tier defaults.

    Design contract:
    - Day 0 uses population defaults (tiered by onboarding).
    - Calibration overwrites with user-specific sleep baselines once enough overnight data exists.
    """
    if onboarding is None:
        freq = "1-3x/week"
    else:
        freq = onboarding.get("exercise_frequency", "1-3x/week")

    # Fixed population defaults per tier (tuned for typical adult RMSSD distributions).
    if freq == "rarely":
        return 32.0, 52.0
    if freq == "4+/week":
        return 60.0, 88.0
    return 44.0, 66.0


async def _load_background_since(
    db_session: AsyncSession,
    user_id: str,
    since: datetime,
) -> list[BackgroundWindowResult]:
    """Load BackgroundWindow rows for user from ``since`` (inclusive), oldest first."""
    result = await db_session.execute(
        select(db.BackgroundWindow)
        .where(db.BackgroundWindow.user_id == user_id)
        .where(db.BackgroundWindow.window_start >= since)
        .order_by(db.BackgroundWindow.window_start)
    )
    rows = result.scalars().all()
    return [
        BackgroundWindowResult(
            user_id       = str(row.user_id),
            window_start  = row.window_start,
            window_end    = row.window_end,
            context       = row.context,
            rmssd_ms      = row.rmssd_ms,
            hr_bpm        = row.hr_bpm,
            lf_hf         = row.lf_hf,
            confidence    = row.confidence,
            acc_mean      = row.acc_mean,
            gyro_mean     = row.gyro_mean,
            n_beats       = row.n_beats,
            artifact_rate = row.artifact_rate,
            is_valid      = row.is_valid,
        )
        for row in rows
    ]


async def _load_all_background_for_model(
    db_session: AsyncSession,
    user_id: str,
    max_days: int = 30,
) -> list[BackgroundWindowResult]:
    """Load all valid BackgroundWindow rows for the last max_days days."""
    cutoff = datetime.now(UTC) - timedelta(days=max_days)
    result = await db_session.execute(
        select(db.BackgroundWindow)
        .where(db.BackgroundWindow.user_id == user_id)
        .where(db.BackgroundWindow.window_start >= cutoff)
        .where(db.BackgroundWindow.is_valid == True)  # noqa: E712
        .order_by(db.BackgroundWindow.window_start)
    )
    rows = result.scalars().all()
    return [
        BackgroundWindowResult(
            user_id       = str(row.user_id),
            window_start  = row.window_start,
            window_end    = row.window_end,
            context       = row.context,
            rmssd_ms      = row.rmssd_ms,
            hr_bpm        = row.hr_bpm,
            lf_hf         = row.lf_hf,
            confidence    = row.confidence,
            acc_mean      = row.acc_mean,
            gyro_mean     = row.gyro_mean,
            n_beats       = row.n_beats,
            artifact_rate = row.artifact_rate,
            is_valid      = row.is_valid,
        )
        for row in rows
    ]


async def _bootstrap_personal_model(
    db_session: AsyncSession,
    user_id: str,
) -> db.PersonalModel:
    """
    Guarantee a PersonalModel row exists for `user_id`.

    If no row exists: create one with tiered population-average seed values
    (derived from onboarding fitness level) so the detection pipeline can run
    immediately on first wear.

    Real-time intra-day refinement has been DISABLED. The model is only updated
    at day-close via `_run_calibration_batch()` on Days 1–3. This prevents a
    single noisy window from permanently poisoning the ceiling.

    Once calibration_locked_at is set (Day 3 close), this function leaves the
    model completely untouched.
    """
    personal = await _load_personal_model(db_session, user_id)
    is_new   = personal is None

    if is_new:
        # Derive seeds from onboarding fitness tier.
        user_result = await db_session.execute(
            select(db.User.onboarding).where(db.User.id == user_id)
        )
        onboarding_json = user_result.scalar_one_or_none()
        seed_floor, seed_ceiling, seed_morning = _seed_from_onboarding(onboarding_json)
        seed_sleep_avg, seed_sleep_ceiling = _seed_sleep_from_onboarding(onboarding_json)
        seed_sleep_ceiling = min(seed_sleep_ceiling, CONFIG.tracking.RMSSD_POPULATION_CEILING)

        personal = db.PersonalModel(
            user_id                      = user_id,
            rmssd_floor                  = seed_floor,
            rmssd_ceiling                = seed_ceiling,
            rmssd_morning_avg            = seed_morning,
            rmssd_sleep_avg              = seed_sleep_avg,
            rmssd_sleep_ceiling          = seed_sleep_ceiling,
            capacity_version             = 0,
            prf_status                   = "PRF_UNKNOWN",
            typical_wake_time            = "07:00",
            typical_sleep_time           = "23:00",
        )
        db_session.add(personal)
        try:
            await db_session.flush()
        except Exception:
            # Unique-constraint race: another concurrent request just created it
            await db_session.rollback()
            personal = await _load_personal_model(db_session, user_id)
            if personal is None:
                raise
        else:
            logger.info(
                "Seeded PersonalModel for user %s (floor=%.1f ceiling=%.1f morning=%.1f)",
                user_id, seed_floor, seed_ceiling, seed_morning,
            )

    # If row exists but sleep baselines are missing (legacy users), seed once from population tier.
    # Calibration will overwrite these when overnight data becomes available.
    if personal is not None and (personal.rmssd_sleep_avg is None or personal.rmssd_sleep_ceiling is None):
        user_result = await db_session.execute(
            select(db.User.onboarding).where(db.User.id == user_id)
        )
        onboarding_json = user_result.scalar_one_or_none()
        seed_sleep_avg, seed_sleep_ceiling = _seed_sleep_from_onboarding(onboarding_json)
        seed_sleep_ceiling = min(seed_sleep_ceiling, CONFIG.tracking.RMSSD_POPULATION_CEILING)
        changed = False
        if personal.rmssd_sleep_avg is None:
            personal.rmssd_sleep_avg = seed_sleep_avg
            changed = True
        if personal.rmssd_sleep_ceiling is None:
            personal.rmssd_sleep_ceiling = seed_sleep_ceiling
            changed = True
        if changed:
            await db_session.flush()

    return personal


# ──────────────────────────────────────────────────────────────────────────────
# Calibration batch (called at close_day() on Days 1–3)
# ──────────────────────────────────────────────────────────────────────────────

async def _run_calibration_batch(
    db_session: AsyncSession,
    user_id: str,
    day_number: int,
    personal: "db.PersonalModel",
) -> None:
    """
    End-of-day calibration pass. Runs on every day_close while
    calibration_locked_at is None (i.e. Days 1, 2, and 3).

    1. Load ALL historical background_windows for the user.
    2. Run 3-pass artifact filter (calibration_filter.py).
    3. Compute floor=P10, ceiling=P90, morning_avg from clean windows.
    4. Apply sanity check (morning_avg >= floor + 10% range).
    5. Write CalibrationSnapshot audit row.
    6. If confidence >= 0.65: update personal_model (committed=True).

    The lock itself is applied by close_day() after this function returns.
    """
    from model.calibration_filter import filter_calibration_windows

    windows = await _load_all_background_for_model(db_session, user_id)
    if not windows:
        logger.warning("Calibration batch day=%d user=%s: no background windows", day_number, user_id)
        return

    # --- Raw stats (before filtering) ---
    raw_rmssd = [w.rmssd_ms for w in windows if w.rmssd_ms is not None]
    rmssd_floor_raw   = float(np.percentile(raw_rmssd, 10)) if len(raw_rmssd) >= 3 else None
    rmssd_ceiling_raw = float(np.percentile(raw_rmssd, 90)) if len(raw_rmssd) >= 3 else None

    # --- 3-pass artifact filter ---
    filter_result = filter_calibration_windows(windows)
    clean = filter_result.clean_windows

    if not clean:
        logger.warning(
            "Calibration batch day=%d user=%s: all %d windows rejected by filter",
            day_number, user_id, len(windows),
        )
        return

    clean_rmssd = [w.rmssd_ms for w in clean if w.rmssd_ms is not None]

    rmssd_floor_clean   = float(np.percentile(clean_rmssd, 10)) if len(clean_rmssd) >= 3 else rmssd_floor_raw
    rmssd_ceiling_clean = float(np.percentile(clean_rmssd, 90)) if len(clean_rmssd) >= 3 else rmssd_ceiling_raw
    # Extra hard-cap: 110ms is the 99th pct of healthy adult RMSSD
    if rmssd_ceiling_clean is not None:
        rmssd_ceiling_clean = min(rmssd_ceiling_clean, 110.0)

    # --- morning_avg: derived from floor+ceiling range (no morning-window dependency) ---
    # Formula: floor + 37% of range — matches the moderate-tier population seed ratio.
    # Owned exclusively here; no other code path may overwrite this field.
    rmssd_morning_avg_clean: Optional[float] = (
        round(rmssd_floor_clean + 0.37 * (rmssd_ceiling_clean - rmssd_floor_clean), 1)
        if rmssd_floor_clean is not None and rmssd_ceiling_clean is not None
        else None
    )

    # --- Write audit snapshot (committed=False initially) ---
    snap = db.CalibrationSnapshot(
        user_id                 = user_id,
        day_number              = day_number,
        rmssd_floor_raw         = rmssd_floor_raw,
        rmssd_ceiling_raw       = rmssd_ceiling_raw,
        rmssd_morning_avg_raw   = None,           # no longer measured separately
        rmssd_floor_clean       = rmssd_floor_clean,
        rmssd_ceiling_clean     = rmssd_ceiling_clean,
        rmssd_morning_avg_clean = rmssd_morning_avg_clean,
        windows_total           = filter_result.windows_total,
        windows_rejected        = filter_result.rejected_count,
        confidence              = filter_result.confidence,
        committed               = False,
        sanity_passed           = True,           # formula always satisfies the range constraint
    )
    db_session.add(snap)

    # --- Sleep scoring v2: compute sleep baseline from calibration windows ---
    # Only fires when band was worn overnight (>= 12 windows = 60 min sleep data).
    sleep_wins = [
        w for w in windows
        if w.context == "sleep" and w.rmssd_ms is not None and w.is_valid
    ]
    rmssd_sleep_avg_clean: Optional[float] = None
    if len(sleep_wins) >= 12:
        sleep_rmssd_vals = [w.rmssd_ms for w in sleep_wins]
        rmssd_sleep_avg_clean = float(np.median(sleep_rmssd_vals))
        rmssd_sleep_ceiling_clean = float(np.percentile(sleep_rmssd_vals, 90))
    else:
        rmssd_sleep_ceiling_clean = None
    snap.sleep_windows_count  = len(sleep_wins)
    snap.rmssd_sleep_avg_clean = round(rmssd_sleep_avg_clean, 1) if rmssd_sleep_avg_clean is not None else None
    snap.rmssd_sleep_ceiling_clean = (
        round(rmssd_sleep_ceiling_clean, 1) if rmssd_sleep_ceiling_clean is not None else None
    )

    # Resting HR for Phase 2 stress corroboration (median over clean background windows)
    clean_bg_hr = [
        w.hr_bpm for w in clean
        if getattr(w, "context", None) == "background" and w.hr_bpm is not None
    ]
    resting_hr_median: Optional[float] = None
    if len(clean_bg_hr) >= 3:
        resting_hr_median = float(np.median(clean_bg_hr))

    # --- Update personal model if confidence is adequate ---
    if filter_result.confidence >= 0.65 and rmssd_floor_clean is not None and rmssd_ceiling_clean is not None:
        personal.rmssd_floor                 = round(rmssd_floor_clean, 1)
        personal.rmssd_ceiling               = round(rmssd_ceiling_clean, 1)
        personal.rmssd_morning_avg           = round(rmssd_morning_avg_clean, 1)  # always set with floor+ceiling
        if resting_hr_median is not None:
            personal.rmssd_resting_hr_bpm = round(resting_hr_median, 1)
        # Persist sleep baseline if enough overnight data was available
        if rmssd_sleep_avg_clean is not None:
            personal.rmssd_sleep_avg     = round(rmssd_sleep_avg_clean, 1)
            personal.rmssd_sleep_ceiling = round(rmssd_sleep_ceiling_clean, 1)
            logger.info(
                "Calibration sleep baseline day=%d user=%s: sleep_avg=%.1f sleep_ceil=%.1f "
                "from %d windows",
                day_number, user_id, rmssd_sleep_avg_clean, rmssd_sleep_ceiling_clean, len(sleep_wins),
            )
        else:
            logger.info(
                "Calibration sleep baseline day=%d user=%s: skipped — only %d sleep windows "
                "(need >= 12). Band not worn overnight.",
                day_number, user_id, len(sleep_wins),
            )
        snap.committed = True
        await db_session.flush()

    logger.info(
        "Calibration batch day=%d user=%s: raw_ceil=%.1f clean_ceil=%.1f "
        "rejected=%d/%d confidence=%.2f committed=%s",
        day_number, user_id,
        rmssd_ceiling_raw or 0.0, rmssd_ceiling_clean or 0.0,
        filter_result.rejected_count, filter_result.windows_total,
        filter_result.confidence, snap.committed,
    )


# ──────────────────────────────────────────────────────────────────────────────
# TrackingService
# ──────────────────────────────────────────────────────────────────────────────

class TrackingService:
    """
    Orchestrates the tracking pipeline for a single user.

    Typical call sequence
    ─────────────────────
    Background watcher (called every ~5 min):
        svc = TrackingService(db, user_id)
        await svc.ingest_background_window(ppi_ms, timestamps, window_start, window_end, context)

    Day close (called once, triggered by sleep detection):
        svc = TrackingService(db, user_id)
        result = await svc.close_day(target_date)
    """

    def __init__(
        self,
        db_session: AsyncSession,
        user_id: str,
        session_factory: Optional[Any] = None,
        llm_client: Optional[Any] = None,
    ):
        self._db              = db_session
        self._uid             = user_id
        self._session_factory = session_factory
        self._llm_client      = llm_client
        self._morning_bundle  = MorningBundleOrchestrator(session_factory, llm_client)

    async def _resolve_reset_anchor_utc(
        self,
        ref_ts_utc: datetime,
        personal: Optional[db.PersonalModel] = None,
    ) -> datetime:
        """
        Morning reset anchor in UTC.
        - Uses user's historical wake time when available.
        - Falls back to 07:00 in STRESS_STATE_TIMEZONE.
        """
        if personal is None:
            personal = await _bootstrap_personal_model(self._db, self._uid)

        local_tz = ZoneInfo(CONFIG.tracking.STRESS_STATE_TIMEZONE)
        now_local = ref_ts_utc.astimezone(local_tz)

        hhmm = _parse_hhmm(getattr(personal, "typical_wake_time", None))
        anchor_h, anchor_m = hhmm if hhmm is not None else (7, 0)

        anchor_local = datetime(
            now_local.year,
            now_local.month,
            now_local.day,
            anchor_h,
            anchor_m,
            tzinfo=local_tz,
        )
        if now_local < anchor_local:
            anchor_local = anchor_local - timedelta(days=1)
        return anchor_local.astimezone(UTC)

    async def _build_live_snapshot_summary(
        self,
        now_utc: datetime,
        summary_start_utc: datetime,
        stress_pct_raw: float,
        recovery_pct_raw: float,
        net_balance: float,
        personal: db.PersonalModel,
    ) -> DailySummaryResult:
        """Build a lightweight live summary from persisted session snapshot values."""
        calibration_days = await self._count_days_with_data()
        calibration_locked = personal.calibration_locked_at is not None
        return DailySummaryResult(
            user_id=self._uid,
            summary_date=summary_start_utc,
            wake_ts=summary_start_utc,
            sleep_ts=None,
            wake_detection_method="logical_reset_anchor",
            sleep_detection_method=None,
            waking_minutes=max(0.0, (now_utc - summary_start_utc).total_seconds() / 60.0),
            stress_load_score=round(_clamp_pct(stress_pct_raw), 1),
            day_type=None,
            # Snapshot path only stores combined recovery_pct on BandWearSession.
            # Keep waking/sleep split unknown here to avoid mislabeling combined
            # values as waking-only.
            waking_recovery_score=None,
            sleep_recovery_score=None,
            net_balance=round(float(net_balance), 2),
            closing_balance=round(float(net_balance), 2),
            stress_pct_raw=float(stress_pct_raw),
            recovery_pct_raw=float(recovery_pct_raw),
            calibration_days=calibration_days,
            is_estimated=not calibration_locked,
            is_partial_data=True,
        )

    async def _contiguous_sleep_minutes_before_transition(self, wake_transition_start: datetime) -> float:
        """Sum duration of contiguous sleep windows immediately before this transition."""
        total = 0.0
        cur = await self._get_last_background_window_before(wake_transition_start)
        while cur is not None and cur.context == "sleep":
            total += (cur.window_end - cur.window_start).total_seconds() / 60.0
            cur = await self._get_last_background_window_before(cur.window_start)
        return total

    async def _should_perform_morning_cycle_reset(
        self,
        transition_time_utc: datetime,
        personal: db.PersonalModel,
    ) -> tuple[bool, Optional[date]]:
        """
        Nap-safe morning reset: (1) near wake anchor, (2) sleep >= 90 min, (3) one per local day.
        Returns (True, local_date) when all pass; else (False, None).
        """
        tz_name = CONFIG.tracking.STRESS_STATE_TIMEZONE
        if not transition_in_morning_wake_window(
            transition_time_utc,
            getattr(personal, "typical_wake_time", None),
            tz_name,
        ):
            return False, None

        sleep_mins = await self._contiguous_sleep_minutes_before_transition(transition_time_utc)
        if sleep_mins + 1e-6 < MIN_SLEEP_MINUTES_FOR_MORNING_RESET:
            return False, None

        local_tz = ZoneInfo(tz_name)
        d = transition_time_utc.astimezone(local_tz).date()

        uid = parse_uuid(self._uid)
        if uid is None:
            return False, None
        user_row = await self._db.get(db.User, uid)
        if user_row is None:
            return False, None
        if user_row.last_morning_cycle_reset_local_date == d:
            return False, None

        return True, d

    def _anchor_utc_for_local_date(self, local_day: date, personal: db.PersonalModel) -> datetime:
        return anchor_utc_for_local_calendar_date(
            local_day,
            getattr(personal, "typical_wake_time", None),
            CONFIG.tracking.STRESS_STATE_TIMEZONE,
        )

    async def _has_background_window_in_range(
        self,
        start_utc: datetime,
        end_utc: datetime,
    ) -> bool:
        """True if any BackgroundWindow exists with window_start in [start, end)."""
        r = await self._db.execute(
            select(db.BackgroundWindow.id)
            .where(db.BackgroundWindow.user_id == self._uid)
            .where(db.BackgroundWindow.window_start >= start_utc)
            .where(db.BackgroundWindow.window_start < end_utc)
            .limit(1)
        )
        return r.scalar_one_or_none() is not None

    async def _first_background_window_start_in_range(
        self,
        start_utc: datetime,
        end_utc: datetime,
    ) -> Optional[datetime]:
        """Earliest BackgroundWindow.window_start in [start, end), else None."""
        r = await self._db.execute(
            select(db.BackgroundWindow.window_start)
            .where(db.BackgroundWindow.user_id == self._uid)
            .where(db.BackgroundWindow.window_start >= start_utc)
            .where(db.BackgroundWindow.window_start < end_utc)
            .order_by(db.BackgroundWindow.window_start.asc())
            .limit(1)
        )
        return r.scalar_one_or_none()

    async def _should_perform_scenario_b_forced_reset(
        self,
        window_start_utc: datetime,
        personal: db.PersonalModel,
    ) -> tuple[bool, Optional[date]]:
        """
        Scenario B (no band overnight): first background ingest after today's anchor,
        with no windows in [anchor_yesterday, anchor_today) — i.e. no wear across
        that cycle window. Shares one-reset-per-day with Scenario A via
        last_morning_cycle_reset_local_date.

        Trigger: first touch after anchor (ingest), not a separate cron.
        """
        tz_name = CONFIG.tracking.STRESS_STATE_TIMEZONE
        local_tz = ZoneInfo(tz_name)
        d = window_start_utc.astimezone(local_tz).date()

        uid = parse_uuid(self._uid)
        if uid is None:
            return False, None
        user_row = await self._db.get(db.User, uid)
        if user_row is None:
            return False, None
        if user_row.last_morning_cycle_reset_local_date == d:
            return False, None

        anchor_d_utc = self._anchor_utc_for_local_date(d, personal)
        if window_start_utc < anchor_d_utc:
            return False, None

        anchor_prev_utc = self._anchor_utc_for_local_date(d - timedelta(days=1), personal)
        first_pre_anchor = await self._first_background_window_start_in_range(
            anchor_prev_utc,
            anchor_d_utc,
        )
        if first_pre_anchor is not None:
            # If pre-anchor data exists far before anchor, this was overnight wear,
            # so Scenario B must not fire. But if first wear starts only shortly
            # before anchor (e.g. 06:00 for 07:00 anchor), keep Scenario B eligible.
            grace_cutoff = anchor_d_utc - timedelta(
                minutes=SCENARIO_B_PRE_ANCHOR_FIRST_WEAR_GRACE_MINUTES
            )
            if first_pre_anchor < grace_cutoff:
                return False, None
        if await self._has_background_window_in_range(anchor_d_utc, window_start_utc):
            return False, None

        return True, d

    def _schedule_morning_bundle(self) -> None:
        """Morning brief + fresh daily plan (Scenario A and B)."""
        self._morning_bundle.schedule(str(self._uid))

    # ── Ingest ─────────────────────────────────────────────────────────────────

    async def ingest_background_window(
        self,
        ppi_ms: list[float],
        timestamps: list[float],
        window_start: datetime,
        window_end: datetime,
        context: str = "background",
        acc_mean: Optional[float] = None,
        gyro_mean: Optional[float] = None,
    ) -> BackgroundWindowResult:
        """
        Process one 5-min PPI chunk, persist BackgroundWindow, then recompute
        today's stress / recovery windows.

        Also manages BandWearSession lifecycle:
          - Opens a new session if none is open or if the gap since the last
            window exceeds BAND_GAP_CLOSE_MINUTES (90 min) — continuity only.
          - On band-off close: snapshot final scores, mark is_closed=True.
          - On first sleep→background transition within a session: compute and
            lock the opening_balance carry-forward (morning reset Scenario A when
            nap gates pass); Scenario B may fire on new session open when no wear
            in the inter-anchor window.
          - Subsequent sleep→background transitions do NOT reset (locked flag).

        Returns the BackgroundWindowResult for the caller (e.g. live UI push).
        """
        ingest_started = perf_counter()

        # Auto-create the user row if it doesn't exist yet (avoids FK violation
        # on background_windows when the user has never called /user/register).
        await self._db.execute(
            pg_insert(db.User)
            .values(id=self._uid, name="User")
            .on_conflict_do_nothing(index_elements=["id"])
        )

        result = aggregate_background_window(
            user_id      = self._uid,
            ppi_ms       = np.array(ppi_ms, dtype=float),
            ts_start     = window_start,
            ts_end       = window_end,
            context      = context,
            acc_samples  = np.array([acc_mean]) if acc_mean is not None else None,
            gyro_samples = np.array([gyro_mean]) if gyro_mean is not None else None,
        )

        # ── Band wear session management ──────────────────────────────────────
        await self._manage_band_session(window_start, window_end, context)

        # Persist raw window
        row = _to_db_background(result)
        self._db.add(row)
        await self._db.flush()   # get the id without committing

        # Recompute stress + recovery windows spanning the full open band session
        band_session = await self._get_open_band_session()
        recompute_started = perf_counter()
        if band_session is not None:
            session_end = min(datetime.now(UTC), window_end + timedelta(minutes=5))
            await self._recompute_day_windows(band_session.started_at, session_end)
        else:
            day_start = window_start.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end   = day_start + timedelta(days=1)
            await self._recompute_day_windows(day_start, day_end)
        logger.info(
            "perf tracking_recompute user=%s duration_ms=%.2f",
            self._uid,
            (perf_counter() - recompute_started) * 1000.0,
        )

        await self._db.commit()

        # Materialise live score after every successful ingest so the DB always
        # has a current row — UI reads from DB rather than computing on-the-fly.
        try:
            materialise_started = perf_counter()
            await self._materialise_daily_score()
            logger.info(
                "perf tracking_materialise_score user=%s duration_ms=%.2f",
                self._uid,
                (perf_counter() - materialise_started) * 1000.0,
            )
        except Exception as _mat_exc:
            logger.warning("Score materialisation failed user=%s: %s", self._uid, _mat_exc)

        logger.debug("Ingested background window %s–%s valid=%s", window_start, window_end, result.is_valid)
        logger.info(
            "perf tracking_ingest_total user=%s duration_ms=%.2f",
            self._uid,
            (perf_counter() - ingest_started) * 1000.0,
        )
        return result

    # ── Band session helpers ───────────────────────────────────────────────────

    async def _get_open_band_session(self) -> Optional[db.BandWearSession]:
        """Return the current open BandWearSession for this user, or None."""
        result = await self._db.execute(
            select(db.BandWearSession)
            .where(db.BandWearSession.user_id == self._uid)
            .where(db.BandWearSession.is_closed == False)  # noqa: E712
            .order_by(db.BandWearSession.started_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _get_last_background_window_before(
        self, before_ts: datetime
    ) -> Optional[db.BackgroundWindow]:
        """Return the most recent background window strictly before before_ts."""
        result = await self._db.execute(
            select(db.BackgroundWindow)
            .where(db.BackgroundWindow.user_id == self._uid)
            .where(db.BackgroundWindow.window_start < before_ts)
            .order_by(db.BackgroundWindow.window_start.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _manage_band_session(
        self,
        window_start: datetime,
        window_end: datetime,
        context: str,
    ) -> None:
        """
        Core band-session state machine. Called before persisting each window.

        Morning day-turnover (scores + brief + plan) is **only** Scenario A
        (sleep→background with nap gate) or Scenario B (no wear in the inter-anchor
        window, first background after anchor). Gap-based session open/close is for
        ingest continuity only, not an extra reset.

        State transitions:
          - No open session → open one with started_at = window_start.
          - Open session, gap since last window ≤ 90 min → continue session;
            update has_sleep_data if context is sleep;
            check for first sleep→background transition to lock opening_balance.
          - Open session, gap > 90 min → close the session with final scores,
            then open a new one. No carry-forward on band-off close.
        """
        from sqlalchemy import desc as sqldesc
        GAP_MINUTES = CONFIG.tracking.BAND_GAP_CLOSE_MINUTES

        open_session = await self._get_open_band_session()
        prev_window  = await self._get_last_background_window_before(window_start)

        # Determine gap since last window (in minutes)
        gap_minutes: Optional[float] = None
        if prev_window is not None:
            gap_minutes = (window_start - prev_window.window_end).total_seconds() / 60.0

        if open_session is None or (gap_minutes is not None and gap_minutes > GAP_MINUTES):
            # ── Close the current session (if any) then open a new one ─────
            if open_session is not None:
                await self._close_band_session(open_session, carry_forward=False)

            # Morning-reset model: continuity survives gaps until reset anchor.
            # After anchor, next session starts fresh.
            personal = await _bootstrap_personal_model(self._db, self._uid)
            cycle_start_utc = await self._resolve_reset_anchor_utc(window_start, personal)
            last_closed_res = await self._db.execute(
                select(db.BandWearSession)
                .where(db.BandWearSession.user_id == self._uid)
                .where(db.BandWearSession.is_closed == True)  # noqa: E712
                .where(db.BandWearSession.ended_at.isnot(None))
                .order_by(db.BandWearSession.ended_at.desc())
                .limit(1)
            )
            last_closed = last_closed_res.scalar_one_or_none()
            reopen_balance = 0.0
            reopen_locked = False
            if last_closed is not None and last_closed.net_balance is not None:
                if last_closed.ended_at >= cycle_start_utc:
                    reopen_balance = float(last_closed.net_balance)
                    reopen_locked = True

            new_session = db.BandWearSession(
                user_id                = self._uid,
                started_at             = window_start,
                ended_at               = None,
                is_closed              = False,
                has_sleep_data         = (context == "sleep"),
                opening_balance        = reopen_balance,
                opening_balance_locked = reopen_locked,
                wake_locked_at         = window_start if reopen_locked else None,
            )
            self._db.add(new_session)
            await self._db.flush()
            logger.info(
                "BandWearSession opened user=%s started_at=%s (gap=%.1f min after close) opening_balance=%.2f locked=%s",
                self._uid, window_start, gap_minutes or 0.0, reopen_balance, reopen_locked,
            )
            # Scenario B: no overnight band data — first background ingest after anchor.
            if context == "background":
                should_b, cycle_d_b = await self._should_perform_scenario_b_forced_reset(
                    window_start, personal,
                )
                if should_b and cycle_d_b is not None:
                    uid_b = parse_uuid(self._uid)
                    if uid_b is not None:
                        user_row_b = await self._db.get(db.User, uid_b)
                        if user_row_b is not None:
                            user_row_b.last_morning_cycle_reset_local_date = cycle_d_b
                            await self._db.flush()
                    logger.info(
                        "BandWearSession Scenario B forced morning reset user=%s ts=%s",
                        self._uid, window_start,
                    )
                    self._schedule_morning_bundle()
            return

        # ── Continuing an open session ────────────────────────────────────────
        # Update has_sleep_data if this is a sleep window
        if context == "sleep" and not open_session.has_sleep_data:
            open_session.has_sleep_data = True

        # Update ended_at to the latest window end (for gap detection correctness)
        open_session.ended_at = window_end

        # Check for sleep→background transition (nap-safe morning reset only)
        if (
            context == "background"
            and prev_window is not None
            and prev_window.context == "sleep"
        ):
            personal = await _bootstrap_personal_model(self._db, self._uid)
            should_reset, cycle_d = await self._should_perform_morning_cycle_reset(window_start, personal)
            if should_reset and cycle_d is not None:
                # Morning-qualified wake: close prior session and start fresh cycle.
                open_session.ended_at = window_start
                await self._close_band_session(open_session, carry_forward=False)
                new_session = db.BandWearSession(
                    user_id                = self._uid,
                    started_at             = window_start,
                    ended_at               = None,
                    is_closed              = False,
                    has_sleep_data         = False,
                    opening_balance        = 0.0,
                    opening_balance_locked = False,
                    wake_locked_at         = None,
                )
                self._db.add(new_session)
                await self._db.flush()

                uid = parse_uuid(self._uid)
                if uid is not None:
                    user_row = await self._db.get(db.User, uid)
                    if user_row is not None:
                        user_row.last_morning_cycle_reset_local_date = cycle_d
                        await self._db.flush()

                logger.info(
                    "BandWearSession morning reset user=%s wake_ts=%s (new session opened)",
                    self._uid, window_start,
                )
                self._schedule_morning_bundle()
                return
            logger.debug(
                "sleep→background skipped morning reset user=%s ts=%s (nap window or short sleep or duplicate)",
                self._uid, window_start,
            )

        await self._db.flush()

    async def _compute_opening_balance(
        self,
        session_start: datetime,
        wake_ts: datetime,
    ) -> float:
        """
        Compute the net balance for the period [session_start, wake_ts).
        This captures the prior evening stress + any overnight sleep recovery
        that occurred before the user's first detected wakeup.

        Returns a float representing net_balance (positive = net recovery,
        negative = net stress debt carried into the waking period).
        """
        personal = await _bootstrap_personal_model(self._db, self._uid)

        pre_wake_windows = await _load_today_background(
            self._db, self._uid, session_start, wake_ts
        )
        if not pre_wake_windows:
            return 0.0

        morning_rmssd    = personal.rmssd_morning_avg or (
            ((personal.rmssd_floor or 22.0) + (personal.rmssd_ceiling or 65.0)) / 2.0
        )
        capacity_floor   = personal.rmssd_floor   or 22.0
        capacity_ceiling = personal.rmssd_ceiling or 65.0
        capacity_version = personal.capacity_version or 0

        stress_db   = await _load_existing_stress_windows(self._db, self._uid, session_start, wake_ts)
        recovery_db = await _load_existing_recovery_windows(self._db, self._uid, session_start, wake_ts)
        stress_results   = TrackingService._db_stress_to_results_static(stress_db)
        recovery_results = TrackingService._db_recovery_to_results_static(recovery_db)

        # Build minimal boundary for pre-wake period
        boundary = WakeSleepBoundary(
            user_id                = self._uid,
            day_date               = session_start,
            wake_ts                = session_start,
            sleep_ts               = wake_ts,
            wake_detection_method  = "band_on_anchor",
            sleep_detection_method = "sleep_transition",
            waking_minutes         = (wake_ts - session_start).total_seconds() / 60.0,
        )

        calibration_days   = await self._count_days_with_data()
        calibration_locked = personal.calibration_locked_at is not None

        summary = compute_daily_summary(
            user_id              = self._uid,
            summary_date         = session_start,
            background_windows   = pre_wake_windows,
            stress_windows       = stress_results,
            recovery_windows     = recovery_results,
            boundary             = boundary,
            personal_morning_avg = morning_rmssd,
            personal_floor       = capacity_floor,
            personal_ceiling     = capacity_ceiling,
            capacity_version     = capacity_version,
            calibration_days     = calibration_days,
            calibration_locked   = calibration_locked,
            day_type             = None,
            capacity_floor_used  = capacity_floor,
            opening_balance      = 0.0,
            rmssd_sleep_avg      = personal.rmssd_sleep_avg,
            sleep_ceiling        = personal.rmssd_sleep_ceiling,
        )
        return summary.net_balance or 0.0

    async def _close_band_session(
        self,
        session: db.BandWearSession,
        carry_forward: bool,
    ) -> None:
        """
        Finalise a BandWearSession by computing the live summary at close time
        and writing the final scores. Sets is_closed=True.

        carry_forward=False means net_balance is recorded but NOT forwarded
        (band-off close). carry_forward=True would be used for context-triggered
        resets (not currently used — kept for future extensibility).
        """
        # Compute live scores at the moment of close
        live = await self._compute_session_summary(
            session_start   = session.started_at,
            session_end     = session.ended_at or datetime.now(UTC),
            opening_balance = session.opening_balance,
            wake_locked_at  = session.wake_locked_at,
        )

        if live is not None:
            session.stress_pct   = live.stress_pct_raw
            session.recovery_pct = live.recovery_pct_raw
            session.net_balance  = live.net_balance

        # ── Pre-compute per-session metrics over the FULL session window ──────
        # Use the full range (started_at → ended_at) regardless of wake_locked_at
        # so that sleep-context windows are always included.
        session_end_ts = session.ended_at or datetime.now(UTC)
        all_windows = await _load_today_background(
            self._db, self._uid, session.started_at, session_end_ts
        )

        bg_rmssd = [w.rmssd_ms for w in all_windows
                    if w.context == "background" and w.is_valid and w.rmssd_ms is not None]
        bg_hr    = [w.hr_bpm   for w in all_windows
                    if w.context == "background" and w.is_valid and w.hr_bpm is not None]
        sleep_ws = [w for w in all_windows if w.context == "sleep" and w.rmssd_ms is not None]

        session.avg_rmssd_ms      = round(sum(bg_rmssd) / len(bg_rmssd), 1) if bg_rmssd else None
        session.avg_hr_bpm        = round(sum(bg_hr)    / len(bg_hr),    1) if bg_hr    else None
        if sleep_ws:
            sleep_rmssd_vals          = [w.rmssd_ms for w in sleep_ws]
            session.sleep_rmssd_avg_ms = round(sum(sleep_rmssd_vals) / len(sleep_rmssd_vals), 1)
            session.sleep_started_at  = sleep_ws[0].window_start
            session.sleep_ended_at    = sleep_ws[-1].window_end

        session.is_closed = True
        await self._db.flush()

        logger.info(
            "BandWearSession closed user=%s started=%s ended=%s stress=%.1f%% recovery=%.1f%% net=%.2f carry_fwd=%s",
            self._uid,
            session.started_at,
            session.ended_at,
            session.stress_pct or 0.0,
            session.recovery_pct or 0.0,
            session.net_balance or 0.0,
            carry_forward,
        )

    async def _compute_session_summary(
        self,
        session_start: datetime,
        session_end: datetime,
        opening_balance: float,
        wake_locked_at: Optional[datetime] = None,
    ) -> Optional[DailySummaryResult]:
        """Compute a DailySummaryResult over a band session's full window range.

        When wake_locked_at is set (i.e. the session spans overnight and a
        sleep→background carry-forward already happened), only windows from
        wake_locked_at onward are scored. This prevents the pre-wake period
        from being counted twice — once in opening_balance and once here.
        """
        personal = await _bootstrap_personal_model(self._db, self._uid)

        # Use wake_locked_at as the effective start for scoring when present.
        # This scopes stress/recovery to the post-wakeup waking period only.
        score_start = wake_locked_at if wake_locked_at is not None else session_start

        bg_windows = await _load_today_background(self._db, self._uid, score_start, session_end)
        if not bg_windows:
            return None

        morning_rmssd    = personal.rmssd_morning_avg or (
            ((personal.rmssd_floor or 22.0) + (personal.rmssd_ceiling or 65.0)) / 2.0
        )
        capacity_floor   = personal.rmssd_floor   or 22.0
        capacity_ceiling = personal.rmssd_ceiling or 65.0
        capacity_version = personal.capacity_version or 0

        stress_db   = await _load_existing_stress_windows(self._db, self._uid, score_start, session_end)
        recovery_db = await _load_existing_recovery_windows(self._db, self._uid, score_start, session_end)
        stress_results   = TrackingService._db_stress_to_results_static(stress_db)
        recovery_results = TrackingService._db_recovery_to_results_static(recovery_db)

        # Build context transitions for boundary detection
        context_transitions: list[ContextTransition] = []
        prev_ctx: Optional[str] = None
        for w in bg_windows:
            if prev_ctx is not None and w.context != prev_ctx:
                context_transitions.append(ContextTransition(
                    ts=w.window_start, from_context=prev_ctx, to_context=w.context,
                ))
            prev_ctx = w.context

        boundary = detect_wake_sleep_boundary(
            day_date                  = score_start,
            user_id                   = self._uid,
            context_transitions       = context_transitions or None,
            typical_wake_time         = personal.typical_wake_time,
            typical_sleep_time        = personal.typical_sleep_time,
            morning_read_ts           = None,
            last_background_window_ts = bg_windows[-1].window_end,
        )
        # Anchor wake_ts to the first post-wakeup background window.
        # When wake_locked_at is set, bg_windows[0] is already at/after wakeup,
        # so this is always correct regardless of the overnight-session case.
        boundary = WakeSleepBoundary(
            user_id               = self._uid,
            day_date              = score_start,
            wake_ts               = bg_windows[0].window_start,
            sleep_ts              = boundary.sleep_ts,
            wake_detection_method = "band_on_anchor",
            sleep_detection_method= boundary.sleep_detection_method,
            waking_minutes        = (session_end - bg_windows[0].window_start).total_seconds() / 60.0,
        )

        calibration_days   = await self._count_days_with_data()
        calibration_locked = personal.calibration_locked_at is not None

        return compute_daily_summary(
            user_id              = self._uid,
            summary_date         = score_start,
            background_windows   = bg_windows,
            stress_windows       = stress_results,
            recovery_windows     = recovery_results,
            boundary             = boundary,
            personal_morning_avg = morning_rmssd,
            personal_floor       = capacity_floor,
            personal_ceiling     = capacity_ceiling,
            capacity_version     = capacity_version,
            calibration_days     = calibration_days,
            calibration_locked   = calibration_locked,
            day_type             = None,
            capacity_floor_used  = capacity_floor,
            opening_balance      = opening_balance,
            rmssd_sleep_avg      = personal.rmssd_sleep_avg,
            sleep_ceiling        = personal.rmssd_sleep_ceiling,
        )

    @staticmethod
    def _db_stress_to_results_static(rows) -> list[StressWindowResult]:
        out = []
        for row in rows:
            out.append(StressWindowResult(
                user_id          = str(row.user_id),
                started_at       = row.started_at,
                ended_at         = row.ended_at,
                duration_minutes = row.duration_minutes,
                rmssd_min_ms     = row.rmssd_min_ms,
                suppression_pct  = row.suppression_pct,
                stress_contribution_pct = row.stress_contribution_pct,
                suppression_area        = row.suppression_area,
                tag          = row.tag,
                tag_candidate = row.tag_candidate,
                tag_source   = row.tag_source,
                nudge_sent   = row.nudge_sent,
                nudge_responded = row.nudge_responded,
            ))
        return out

    @staticmethod
    def _db_recovery_to_results_static(rows) -> list[RecoveryWindowResult]:
        out = []
        for row in rows:
            out.append(RecoveryWindowResult(
                user_id          = str(row.user_id),
                started_at       = row.started_at,
                ended_at         = row.ended_at,
                duration_minutes = row.duration_minutes,
                context          = row.context,
                rmssd_avg_ms     = row.rmssd_avg_ms,
                recovery_contribution_pct = row.recovery_contribution_pct,
                recovery_area    = row.recovery_area,
                tag              = row.tag,
                tag_source       = row.tag_source,
                zenflow_session_id = row.zenflow_session_id,
            ))
        return out

    async def _assign_readiness_for_row(self, row: db.DailyStressSummary) -> None:
        """
        Set ``readiness_score`` from the **previous** calendar day's stress,
        waking recovery, and sleep recovery (composite formula).
        """
        if row.summary_date is None:
            return
        prev_date = (row.summary_date - timedelta(days=1)).date()
        prev = await self._load_day_summary(prev_date)
        if prev is None:
            row.readiness_score = None
            return
        stress_raw = prev.stress_load_score
        if stress_raw is None:
            row.readiness_score = None
            return
        stress_10 = float(stress_raw) / 10.0
        w = prev.waking_recovery_score
        s = getattr(prev, "sleep_recovery_score", None)
        row.readiness_score = compute_composite_readiness(w, s, stress_10)

    async def _materialise_daily_score(self) -> None:
        """Upsert a DailyStressSummary row for today using the live computation.

        Called after every ingest.  Uses the open BandWearSession as the scope
        so the row is always aligned to the current wear period, not UTC midnight.
        Rows already closed (is_partial_data=False) are left untouched.
        """
        band_session = await self._get_open_band_session()

        if band_session is not None:
            # Key the row to the IST calendar day when the session started so History
            # summary_date aligns with Home "today" for users in STRESS_STATE_TIMEZONE.
            session_date = local_today(band_session.started_at)
            day_start    = datetime(session_date.year, session_date.month, session_date.day, tzinfo=UTC)
        else:
            today     = local_today()
            day_start = datetime(today.year, today.month, today.day, tzinfo=UTC)

        # If the row for this start date is already finalised, nothing to do.
        existing = await self._load_day_summary(day_start.date())
        if existing is not None and not existing.is_partial_data:
            return

        if band_session is not None:
            personal = await _bootstrap_personal_model(self._db, self._uid)
            cycle_start_utc = await self._resolve_reset_anchor_utc(datetime.now(UTC), personal)
            # Product contract: gap-based session reopen must not restart daily scores.
            # Always score live from the active reset-cycle anchor.
            live = await self._compute_session_summary(
                session_start   = cycle_start_utc,
                session_end     = datetime.now(UTC),
                opening_balance = 0.0,
                wake_locked_at  = None,
            )
        else:
            live = await self.compute_live_summary(day_start.date())

        if live is None:
            return  # no data yet

        if existing is None:
            row = db.DailyStressSummary(
                user_id      = self._uid,
                summary_date = day_start,
            )
            self._db.add(row)
        else:
            row = existing

        row.stress_load_score         = live.stress_load_score
        row.day_type                  = live.day_type
        row.wake_ts                   = live.wake_ts
        row.sleep_ts                  = live.sleep_ts
        row.wake_detection_method     = live.wake_detection_method
        row.sleep_detection_method    = live.sleep_detection_method
        row.waking_minutes            = live.waking_minutes
        row.raw_suppression_area      = live.raw_suppression_area
        row.raw_recovery_area_sleep   = live.raw_recovery_area_sleep
        row.raw_recovery_area_zenflow = live.raw_recovery_area_zenflow
        row.raw_recovery_area_daytime = live.raw_recovery_area_daytime
        row.raw_recovery_area_waking  = live.raw_recovery_area_waking
        row.max_possible_suppression  = live.max_possible_suppression
        row.is_estimated              = live.is_estimated
        row.is_partial_data           = True  # live rows are always partial
        row.waking_recovery_score     = live.waking_recovery_score
        row.sleep_recovery_score      = live.sleep_recovery_score
        row.net_balance               = live.net_balance
        row.ns_capacity_used          = live.ns_capacity_used
        row.stress_pct_raw            = live.stress_pct_raw
        row.recovery_pct_raw          = live.recovery_pct_raw
        row.ns_capacity_recovery      = live.ns_capacity_recovery_used

        await self._assign_readiness_for_row(row)

        await self._db.commit()
        logger.debug("Materialised daily score user=%s date=%s net=%.1f",
                     self._uid, day_start.date(), live.net_balance or 0.0)

    # ── Recompute intraday ──────────────────────────────────────────────────────

    async def _recompute_day_windows(
        self,
        day_start: datetime,
        day_end: datetime,
    ) -> None:
        """
        Run detection algorithms over all BackgroundWindows for this day and
        replace existing StressWindow / RecoveryWindow rows with fresh results.
        """
        personal = await _bootstrap_personal_model(self._db, self._uid)

        # Use calibration midpoint as baseline reference when morning_avg is unavailable.
        # (morning reads no longer exist; rmssd_morning_avg retained from prior calibration)
        morning_rmssd = personal.rmssd_morning_avg or (
            ((personal.rmssd_floor or 22.0) + (personal.rmssd_ceiling or 65.0)) / 2.0
        )
        capacity_floor = personal.rmssd_floor
        if capacity_floor is None:
            return

        bg_windows = await _load_today_background(self._db, self._uid, day_start, day_end)

        # Estimate max-possible areas for intraday contribution normalisation.
        # Exact values are computed at day-close (when waking_minutes is known);
        # here we use a conservative 16-hour waking day (960 min).
        _INTRADAY_WAKING_MIN = 960.0
        capacity_ceiling = personal.rmssd_ceiling or (morning_rmssd * 1.5)
        max_suppression = max(
            0.0, (morning_rmssd - capacity_floor) * _INTRADAY_WAKING_MIN
        )
        max_recovery = max(
            0.0, (capacity_ceiling - morning_rmssd) * (_INTRADAY_WAKING_MIN + 480.0)
        )

        # Detect stress windows
        raw_stress = detect_stress_windows(
            windows              = bg_windows,
            personal_morning_avg = morning_rmssd,
            personal_floor       = capacity_floor,
            personal_resting_hr  = getattr(personal, "rmssd_resting_hr_bpm", None),
        )
        raw_stress = compute_stress_contributions(raw_stress, max_suppression)

        # Detect recovery windows
        zenflow_intervals: list[tuple[datetime, datetime, str]] = []
        raw_recovery = detect_recovery_windows(
            windows              = bg_windows,
            personal_morning_avg = morning_rmssd,
            zenflow_session_intervals = zenflow_intervals,
        )
        raw_recovery = compute_recovery_contributions(raw_recovery, max_recovery)

        # Preserve user-confirmed tags across recompute.
        # Detection rows are rebuilt (delete+insert), so row IDs are unstable.
        # We carry user tags forward by matching window time bounds.
        def _win_key(started_at: datetime, ended_at: datetime) -> tuple[datetime, datetime]:
            s = started_at.astimezone(UTC).replace(microsecond=0) if started_at.tzinfo else started_at.replace(tzinfo=UTC, microsecond=0)
            e = ended_at.astimezone(UTC).replace(microsecond=0) if ended_at.tzinfo else ended_at.replace(tzinfo=UTC, microsecond=0)
            return s, e

        # Null out FK references in daily_stress_summaries before deleting windows.
        # Without this, PostgreSQL raises ForeignKeyViolationError because the
        # summary row's top_stress_window_id / top_recovery_window_id still points
        # to the old window rows we're about to delete.
        existing_summary = await self._load_day_summary(day_start.date())
        if existing_summary is not None:
            existing_summary.top_stress_window_id   = None
            existing_summary.top_recovery_window_id = None
            await self._db.flush()

        # Delete old windows for today and re-insert
        existing_s = await _load_existing_stress_windows(self._db, self._uid, day_start, day_end)
        tagged_stress_by_key: dict[tuple[datetime, datetime], tuple[str, str | None]] = {}
        prior_stress_tagged: list[tuple[datetime, datetime, str, str]] = []
        for row in existing_s:
            tag = getattr(row, "tag", None)
            source = getattr(row, "tag_source", None)
            if tag and source and str(source).startswith("user"):
                tagged_stress_by_key[_win_key(row.started_at, row.ended_at)] = (str(tag), source)
                prior_stress_tagged.append((row.started_at, row.ended_at, str(tag), source))
        await self._db.execute(
            delete(db.StressWindow)
            .where(db.StressWindow.user_id == self._uid)
            .where(db.StressWindow.started_at >= day_start)
            .where(db.StressWindow.started_at < day_end)
        )

        existing_r = await _load_existing_recovery_windows(self._db, self._uid, day_start, day_end)
        tagged_recovery_by_key: dict[tuple[datetime, datetime], tuple[str, str | None]] = {}
        prior_recovery_tagged: list[tuple[datetime, datetime, str, str]] = []
        for row in existing_r:
            tag = getattr(row, "tag", None)
            source = getattr(row, "tag_source", None)
            if tag and source and str(source).startswith("user"):
                tagged_recovery_by_key[_win_key(row.started_at, row.ended_at)] = (str(tag), source)
                prior_recovery_tagged.append((row.started_at, row.ended_at, str(tag), source))
        await self._db.execute(
            delete(db.RecoveryWindow)
            .where(db.RecoveryWindow.user_id == self._uid)
            .where(db.RecoveryWindow.started_at >= day_start)
            .where(db.RecoveryWindow.started_at < day_end)
        )

        for sw in raw_stress:
            key = _win_key(sw.started_at, sw.ended_at)
            t, src = _carry_user_tag_from_prior_intervals(
                started_at=sw.started_at,
                ended_at=sw.ended_at,
                exact_key=key,
                exact_map=tagged_stress_by_key,
                prior_intervals=prior_stress_tagged,
            )
            if t is not None:
                sw.tag = t
                sw.tag_source = src or "user_confirmed"

        for sw in raw_stress:
            self._db.add(_to_db_stress(sw))

        for rw in raw_recovery:
            key = _win_key(rw.started_at, rw.ended_at)
            t, src = _carry_user_tag_from_prior_intervals(
                started_at=rw.started_at,
                ended_at=rw.ended_at,
                exact_key=key,
                exact_map=tagged_recovery_by_key,
                prior_intervals=prior_recovery_tagged,
            )
            if t is not None:
                rw.tag = t
                rw.tag_source = src or "user_confirmed"
        for rw in raw_recovery:
            self._db.add(_to_db_recovery(rw))

    # ── Calibration + plan assessment (replaces close_day) ────────────────────

    async def run_calibration_for_date(self, target_date: date) -> None:
        """
        Run the calibration batch for target_date and apply the calibration lock
        when the threshold is reached.  Called from the nightly rebuild job
        instead of the old close_day().
        """
        personal = await _bootstrap_personal_model(self._db, self._uid)

        # ── Finalize past DailyStressSummary rows ─────────────────────────────
        # Live rows are always written with is_partial_data=True during the day.
        # The nightly job is the correct close point — flip every row up to and
        # including target_date so that _count_days_with_data() returns the real
        # count instead of 0 (the root cause of calibration lock never firing).
        day_cutoff = datetime(
            target_date.year, target_date.month, target_date.day, tzinfo=UTC
        ) + timedelta(days=1)
        stale_res = await self._db.execute(
            select(db.DailyStressSummary)
            .where(db.DailyStressSummary.user_id == self._uid)
            .where(db.DailyStressSummary.summary_date < day_cutoff)
            .where(db.DailyStressSummary.is_partial_data == True)  # noqa: E712
        )
        stale_rows = stale_res.scalars().all()
        for row in stale_rows:
            row.is_partial_data = False
        if stale_rows:
            await self._db.flush()
            logger.info(
                "Finalized %d DailyStressSummary rows user=%s up_to=%s",
                len(stale_rows), self._uid, target_date,
            )

        calibration_days = await self._count_days_with_data()

        if personal.calibration_locked_at is None:
            await _run_calibration_batch(self._db, self._uid, calibration_days, personal)
            await self._db.refresh(personal)

        calibration_locked = calibration_days >= CONFIG.model.BASELINE_STABLE_DAYS
        if calibration_locked and personal.calibration_locked_at is None:
            personal.calibration_locked_at = datetime.now(UTC)
            await self._db.flush()
            logger.info(
                "Calibration locked for user %s after %d days",
                self._uid, calibration_days,
            )

        await self._db.commit()
        logger.debug(
            "run_calibration_for_date user=%s date=%s days=%d locked=%s",
            self._uid, target_date, calibration_days, calibration_locked,
        )

    async def assess_plan_adherence(self, target_date: date) -> None:
        """
        Run the evening plan adherence assessment for target_date.
        Writes per-item adherence_score to DailyPlan.items_json.
        Called from the nightly rebuild job.
        """
        try:
            from api.services.plan_service import PlanService
            from coach.assessor import assess_daily_adherence
            from sqlalchemy.orm.attributes import flag_modified
            plan_svc = PlanService(self._db, None)
            today_dt = datetime(target_date.year, target_date.month, target_date.day, tzinfo=UTC)
            plan_row = await plan_svc._load_today_row(self._uid, today_dt)
            if plan_row and plan_row.items_json:
                plan_row.items_json = assess_daily_adherence(plan_row.items_json)
                flag_modified(plan_row, "items_json")
                await self._db.commit()
        except Exception as e:
            logger.warning("Failed plan assessment user=%s date=%s: %s", self._uid, target_date, e)

    # ── Tag update ─────────────────────────────────────────────────────────────

    async def update_window_tag(
        self,
        window_id: str,
        window_type: str,  # "stress" | "recovery"
        tag: str,
    ) -> None:
        """
        Apply a user-confirmed tag to a stress or recovery window.
        Called by POST /tracking/tag-window.
        """
        if window_type == "stress":
            result = await self._db.execute(
                select(db.StressWindow).where(db.StressWindow.id == window_id)
            )
            row = result.scalar_one_or_none()
            if row:
                row.tag        = tag
                row.tag_source = "user_confirmed"
        elif window_type == "recovery":
            result = await self._db.execute(
                select(db.RecoveryWindow).where(db.RecoveryWindow.id == window_id)
            )
            row = result.scalar_one_or_none()
            if row:
                row.tag        = tag
                row.tag_source = "user_confirmed"
        else:
            raise ValueError(f"Unknown window_type: {window_type!r}")

        await self._db.commit()

    # ── Read helpers ───────────────────────────────────────────────────────────

    async def get_daily_summary(
        self, target_date: date
    ) -> Optional[db.DailyStressSummary]:
        return await self._load_day_summary(target_date)

    async def resolve_readiness_for_calendar_date(self, target: date) -> Optional[float]:
        """
        Readiness shown for calendar day ``target``: stored on that day's summary row
        (written at materialise from prior day), or computed on the fly from the
        prior day's metrics (same as plan_service). Used when the API returns a
        live ``DailySummaryResult`` that has no ``readiness_score`` field.
        """
        t_row = await self._load_day_summary(target)
        if t_row is not None and t_row.readiness_score is not None:
            return float(t_row.readiness_score)
        y = target - timedelta(days=1)
        y_row = await self._load_day_summary(y)
        if y_row is None or y_row.stress_load_score is None:
            return None
        return compute_composite_readiness(
            y_row.waking_recovery_score,
            getattr(y_row, "sleep_recovery_score", None),
            float(y_row.stress_load_score) / 10.0,
        )

    async def get_personal_model(self) -> Optional[db.PersonalModel]:
        """Return the user's PersonalModel row (or None if it doesn't exist yet)."""
        return await _load_personal_model(self._db, self._uid)

    async def get_stress_state(self, include_cohort: bool = False) -> StressStateResult:
        """
        Point-in-time stress zone + short trend for Home UX (Phase 2–3, 7).

        Read-only: does not create PersonalModel rows (uses onboarding tier seeds
        when no model exists yet).
        """
        cfg = CONFIG.tracking
        now = datetime.now(UTC)
        since = now - timedelta(days=cfg.STRESS_STATE_HISTORY_DAYS)
        windows = await _load_background_since(self._db, self._uid, since)

        uid = parse_uuid(self._uid)
        onboarding_json: Optional[dict] = None
        age_years: Optional[int] = None
        if uid is not None:
            user_row = await self._db.get(db.User, uid)
            if user_row is not None and isinstance(user_row.onboarding, dict):
                onboarding_json = user_row.onboarding
                ag = onboarding_json.get("age")
                if isinstance(ag, int):
                    age_years = ag

        personal = await _load_personal_model(self._db, self._uid)
        if personal is None:
            floor, ceiling, morning = _seed_from_onboarding(onboarding_json)
            morning_ref = float(morning)
            ceil_ms = float(ceiling)
        else:
            floor = float(personal.rmssd_floor or 22.0)
            ceil_ms = float(personal.rmssd_ceiling) if personal.rmssd_ceiling else None
            mr = personal.rmssd_morning_avg
            if mr is None or mr <= 0:
                morning_ref = (floor + (ceil_ms or 65.0)) / 2.0
            else:
                morning_ref = float(mr)

        tod_med = median_rmssd_same_weekday_hour(
            windows,
            now,
            cfg.STRESS_STATE_TIMEZONE,
            cfg.STRESS_STATE_TOD_MIN_BUCKET_SAMPLES,
        )
        w_blend = cfg.STRESS_STATE_TOD_BLEND_MORNING_WEIGHT
        if tod_med is not None:
            index_ref = w_blend * morning_ref + (1.0 - w_blend) * tod_med
            ref_type = "time_of_day"
            tod_out: Optional[float] = tod_med
        else:
            index_ref = morning_ref
            ref_type = "morning_avg"
            tod_out = None

        result = compute_stress_state(
            now=now,
            windows_history=windows,
            personal_floor=floor,
            personal_ref_morning=morning_ref,
            index_reference_ms=index_ref,
            reference_type=ref_type,
            personal_ceiling=ceil_ms,
            ema_alpha=cfg.STRESS_STATE_EMA_ALPHA,
            recent_span_hours=cfg.STRESS_STATE_RECENT_SPAN_HOURS,
            trend_lookback_minutes=cfg.STRESS_STATE_TREND_LOOKBACK_MINUTES,
            trend_delta_threshold=cfg.STRESS_STATE_TREND_DELTA,
            min_history_for_percentiles=cfg.STRESS_STATE_MIN_SAMPLES_PERCENTILE,
            time_of_day_reference_ms=tod_out,
        )

        if include_cohort:
            opt_in = bool(onboarding_json and onboarding_json.get("compare_to_peers") is True)
            ce, cb, cd = build_cohort_insight(
                include_requested=True,
                user_opt_in=opt_in,
                stress_index=result.stress_now_index,
                age_years=age_years,
            )
            result = replace(
                result,
                cohort_enabled=ce,
                cohort_band=cb,
                cohort_disclaimer=cd,
            )

        return result

    async def _load_day_summary_finalized_in_utc_bounds(
        self,
        start_ts: datetime,
        end_ts: datetime,
    ) -> Optional[db.DailyStressSummary]:
        """Like _load_day_summary_by_utc_bounds but only finalized rows (stable for recap)."""
        result = await self._db.execute(
            select(db.DailyStressSummary)
            .where(db.DailyStressSummary.user_id == self._uid)
            .where(db.DailyStressSummary.summary_date >= start_ts)
            .where(db.DailyStressSummary.summary_date < end_ts)
            .where(db.DailyStressSummary.is_partial_data == False)  # noqa: E712
            .order_by(db.DailyStressSummary.summary_date.desc())
        )
        return result.scalars().first()

    async def get_current_cycle_local_date(self) -> date:
        """
        Local date label for the active morning-reset cycle (Scenario A/B).

        After a reset, matches ``users.last_morning_cycle_reset_local_date`` and
        stays stable across IST midnight until the next reset. If the user has
        never had a qualifying reset, falls back to calendar ``local_today()``.
        """
        uid = parse_uuid(self._uid)
        if uid is None:
            return local_today()
        user_row = await self._db.get(db.User, uid)
        if user_row is None or user_row.last_morning_cycle_reset_local_date is None:
            return local_today()
        return user_row.last_morning_cycle_reset_local_date

    async def resolve_strict_recap_anchor(self) -> tuple[date, datetime, datetime]:
        """
        Completed-cycle day for morning recap + UTC [start, end) bounds.

        Recap follows morning-reset semantics with stale-reset protection:
        - If today's reset has fired (last_reset >= local_today), show prior
          completed cycle: ``last_reset - 1 day``.
        - If reset has not fired yet today and last_reset == yesterday, show
          ``last_reset`` itself.
        - If last_reset is older than yesterday (stale), fallback to calendar
          yesterday to avoid pinning recap to an old day.
        - If no reset exists yet, fallback to IST calendar yesterday.
        """
        recap_for_date = recap_yesterday_local_date()
        today_local = local_today()
        uid = parse_uuid(self._uid)
        if uid is not None:
            user_row = await self._db.get(db.User, uid)
            if user_row is not None and user_row.last_morning_cycle_reset_local_date is not None:
                rd = user_row.last_morning_cycle_reset_local_date
                if rd >= today_local:
                    recap_for_date = rd - timedelta(days=1)
                elif rd == (today_local - timedelta(days=1)):
                    recap_for_date = rd
                else:
                    recap_for_date = recap_yesterday_local_date()
        start_ts, end_ts = utc_instant_bounds_for_local_calendar_date(recap_for_date)
        return recap_for_date, start_ts, end_ts

    async def load_strict_recap_daily_row(self) -> Optional[db.DailyStressSummary]:
        """
        Strict DailyStressSummary row for recap_for_date (IST day bounds only).

        No snapshot / inferred fallback — if the row is missing, downstream surfaces
        (recap, coach brief, plan) must stay empty for this cycle.
        """
        start_ts, end_ts = (await self.resolve_strict_recap_anchor())[1:3]
        return await self._load_day_summary_by_utc_bounds(start_ts, end_ts)

    async def has_strict_yesterday_summary(self) -> bool:
        """True iff a DB row exists for the strict recap day (cycle-anchored when reset exists)."""
        row = await self.load_strict_recap_daily_row()
        return row is not None

    async def _compute_recap_snapshot_for_ist_bounds(
        self,
        start_ts: datetime,
        end_ts: datetime,
        ist_calendar_date: date,
    ) -> Optional[DailySummaryResult]:
        """
        Read-only snapshot for [start_ts, end_ts) using only windows in that range.

        Deprecated for morning recap (strict row-only contract); kept for tests or
        ad-hoc diagnostics.
        """
        local_tz = ZoneInfo(CONFIG.tracking.STRESS_STATE_TIMEZONE)
        prev_ist = ist_calendar_date - timedelta(days=1)
        prev_start = datetime(prev_ist.year, prev_ist.month, prev_ist.day, tzinfo=local_tz).astimezone(UTC)
        prev_end = start_ts
        prev_row = await self._load_day_summary_finalized_in_utc_bounds(prev_start, prev_end)
        opening_bal = 0.0
        if prev_row is not None:
            if prev_row.closing_balance is not None:
                opening_bal = float(prev_row.closing_balance)
            elif prev_row.net_balance is not None:
                opening_bal = float(prev_row.net_balance)

        bg_windows = await _load_today_background(self._db, self._uid, start_ts, end_ts)
        if not bg_windows:
            return None

        personal = await _bootstrap_personal_model(self._db, self._uid)
        morning_rmssd = personal.rmssd_morning_avg or (
            ((personal.rmssd_floor or 22.0) + (personal.rmssd_ceiling or 65.0)) / 2.0
        )
        capacity_floor = personal.rmssd_floor or 22.0
        capacity_ceiling = personal.rmssd_ceiling or 65.0
        capacity_version = personal.capacity_version or 0

        stress_db = await _load_existing_stress_windows(self._db, self._uid, start_ts, end_ts)
        recovery_db = await _load_existing_recovery_windows(self._db, self._uid, start_ts, end_ts)
        stress_results = self._db_stress_to_results(stress_db)
        recovery_results = self._db_recovery_to_results(recovery_db)

        context_transitions: list[ContextTransition] = []
        prev_ctx: Optional[str] = None
        for w in bg_windows:
            if prev_ctx is not None and w.context != prev_ctx:
                context_transitions.append(ContextTransition(
                    ts=w.window_start, from_context=prev_ctx, to_context=w.context,
                ))
            prev_ctx = w.context

        last_bg_ts = bg_windows[-1].window_end
        boundary = detect_wake_sleep_boundary(
            day_date=start_ts,
            user_id=self._uid,
            context_transitions=context_transitions or None,
            typical_wake_time=personal.typical_wake_time,
            typical_sleep_time=personal.typical_sleep_time,
            morning_read_ts=None,
            last_background_window_ts=min(last_bg_ts, end_ts),
        )
        band_on_ts = bg_windows[0].window_start
        elapsed = (min(end_ts, last_bg_ts) - band_on_ts).total_seconds() / 60.0
        boundary = WakeSleepBoundary(
            user_id=self._uid,
            day_date=start_ts,
            wake_ts=band_on_ts,
            sleep_ts=boundary.sleep_ts,
            wake_detection_method="band_on_anchor",
            sleep_detection_method=boundary.sleep_detection_method,
            waking_minutes=max(0.0, elapsed),
        )

        calibration_days = await self._count_days_with_data()
        calibration_locked = personal.calibration_locked_at is not None

        return compute_daily_summary(
            user_id=self._uid,
            summary_date=start_ts,
            background_windows=bg_windows,
            stress_windows=stress_results,
            recovery_windows=recovery_results,
            boundary=boundary,
            personal_morning_avg=morning_rmssd,
            personal_floor=capacity_floor,
            personal_ceiling=capacity_ceiling,
            capacity_version=capacity_version,
            calibration_days=calibration_days,
            calibration_locked=calibration_locked,
            day_type=None,
            capacity_floor_used=capacity_floor,
            opening_balance=opening_bal,
            rmssd_sleep_avg=personal.rmssd_sleep_avg,
            sleep_ceiling=personal.rmssd_sleep_ceiling,
        )

    async def get_morning_recap(self) -> dict:
        """Reset-anchored recap day + whether to show recap card (Phase 5).

        Strict IST-day lookup only: if there is no DailyStressSummary row for
        ``for_date``, summary is null (no inferred snapshot).
        """
        recap_for_date, _, _ = await self.resolve_strict_recap_anchor()

        uid = parse_uuid(self._uid)
        ack_d: Optional[date] = None
        if uid is not None:
            res = await self._db.execute(
                select(db.User.morning_recap_ack_for_date).where(db.User.id == uid)
            )
            row_user = res.one_or_none()
            if row_user is not None:
                ack_d = row_user[0]

        row = await self.load_strict_recap_daily_row()

        should_show = row is not None and ack_d != recap_for_date
        summary: Optional[dict] = None
        if row is not None:
            # Sleep recovery is persisted as a display score on the daily summary row
            # (computed via the v2 log-space formula in tracking/daily_summarizer).
            sleep_recovery_score: Optional[float] = getattr(row, "sleep_recovery_score", None)
            summary = {
                "stress_load_score": row.stress_load_score,
                "recovery_score": getattr(row, "waking_recovery_score", None),
                "waking_recovery_score": getattr(row, "waking_recovery_score", None),
                "sleep_recovery_score": sleep_recovery_score,
                "net_balance": getattr(row, "net_balance", None),
                "day_type": row.day_type,
                "is_estimated": row.is_estimated,
                "is_partial_data": row.is_partial_data,
                "sleep_recovery_area": round(row.raw_recovery_area_sleep, 2),
                "closing_balance": getattr(row, "closing_balance", None),
                **contract_metadata_for_row(
                    is_estimated=bool(row.is_estimated),
                    is_partial_data=bool(getattr(row, "is_partial_data", False)),
                    calibration_days=int(getattr(row, "calibration_days", 0) or 0),
                    summary_source="persisted_row",
                ),
            }

        return {
            "for_date": recap_for_date.isoformat(),
            "should_show": should_show,
            "acknowledged_for_date": ack_d == recap_for_date,
            "summary": summary,
        }

    async def ack_morning_recap(self, for_date: date) -> None:
        """Persist dismiss for morning recap (cross-device)."""
        uid = parse_uuid(self._uid)
        if uid is None:
            return
        user_row = await self._db.get(db.User, uid)
        if user_row is None:
            return
        user_row.morning_recap_ack_for_date = for_date
        await self._db.commit()

    async def compute_live_summary(
        self, target_date: date
    ) -> Optional[DailySummaryResult]:
        """
        Compute the three scores on-the-fly from existing intraday windows
        WITHOUT writing anything to the database.

        When an open BandWearSession exists, the query window spans from
        session.started_at to now — regardless of UTC day boundaries.  This
        prevents the 5:30 AM IST reset caused by the UTC midnight flip.

        When no open session exists (band not worn), falls back to the UTC
        calendar day for target_date (historical/closed-day view).

        Always marks is_partial_data=True since the day is not finalized.
        """
        now = datetime.now(UTC)

        # Prefer band-session scope over UTC calendar day
        band_session = await self._get_open_band_session()
        if band_session is not None:
            personal = await _bootstrap_personal_model(self._db, self._uid)
            cycle_start_utc = await self._resolve_reset_anchor_utc(now, personal)
            # Product contract: no gap/new-session reset.
            # Compute over the whole active cycle (anchor → now), not open-session start.
            return await self._compute_session_summary(
                session_start   = cycle_start_utc,
                session_end     = now,
                opening_balance = 0.0,
                wake_locked_at  = None,
            )

        personal = await _bootstrap_personal_model(self._db, self._uid)
        cycle_start_utc = await self._resolve_reset_anchor_utc(now, personal)

        # No open session: show last closed snapshot until morning reset anchor.
        # After anchor (and without new wear data), expose explicit zero baseline.
        last_closed_res = await self._db.execute(
            select(db.BandWearSession)
            .where(db.BandWearSession.user_id == self._uid)
            .where(db.BandWearSession.is_closed == True)  # noqa: E712
            .where(db.BandWearSession.ended_at.isnot(None))
            .order_by(db.BandWearSession.ended_at.desc())
            .limit(1)
        )
        last_closed = last_closed_res.scalar_one_or_none()
        if (
            last_closed is not None
            and last_closed.ended_at is not None
            and last_closed.ended_at >= cycle_start_utc
            and last_closed.net_balance is not None
        ):
            return await self._build_live_snapshot_summary(
                now_utc=now,
                summary_start_utc=cycle_start_utc,
                stress_pct_raw=float(last_closed.stress_pct or 0.0),
                recovery_pct_raw=float(last_closed.recovery_pct or 0.0),
                net_balance=float(last_closed.net_balance or 0.0),
                personal=personal,
            )

        return await self._build_live_snapshot_summary(
            now_utc=now,
            summary_start_utc=cycle_start_utc,
            stress_pct_raw=0.0,
            recovery_pct_raw=0.0,
            net_balance=0.0,
            personal=personal,
        )

    async def get_stress_windows(
        self, target_date: date
    ) -> list[db.StressWindow]:
        day_start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=UTC)
        day_end   = day_start + timedelta(days=1)
        return await _load_existing_stress_windows(self._db, self._uid, day_start, day_end)

    async def get_recovery_windows(
        self, target_date: date
    ) -> list[db.RecoveryWindow]:
        day_start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=UTC)
        day_end   = day_start + timedelta(days=1)
        return await _load_existing_recovery_windows(self._db, self._uid, day_start, day_end)

    async def get_waveform(
        self, target_date: date
    ) -> list[BackgroundWindowResult]:
        day_start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=UTC)
        day_end   = day_start + timedelta(days=1)
        return await _load_today_background(self._db, self._uid, day_start, day_end)

    async def get_history(
        self, days: int = 28
    ) -> list[db.DailyStressSummary]:
        cutoff = datetime.now(UTC) - timedelta(days=days)
        result = await self._db.execute(
            select(db.DailyStressSummary)
            .where(db.DailyStressSummary.user_id == self._uid)
            .where(db.DailyStressSummary.summary_date >= cutoff)
            .order_by(db.DailyStressSummary.summary_date.desc())
        )
        return result.scalars().all()

    # ── Private helpers ────────────────────────────────────────────────────────

    async def _load_day_summary(
        self, target_date: date
    ) -> Optional[db.DailyStressSummary]:
        day_start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=UTC)
        day_end   = day_start + timedelta(days=1)
        result = await self._db.execute(
            select(db.DailyStressSummary)
            .where(db.DailyStressSummary.user_id == self._uid)
            .where(db.DailyStressSummary.summary_date >= day_start)
            .where(db.DailyStressSummary.summary_date < day_end)
        )
        return result.scalar_one_or_none()

    async def _load_day_summary_by_utc_bounds(
        self,
        start_ts: datetime,
        end_ts: datetime,
    ) -> Optional[db.DailyStressSummary]:
        result = await self._db.execute(
            select(db.DailyStressSummary)
            .where(db.DailyStressSummary.user_id == self._uid)
            .where(db.DailyStressSummary.summary_date >= start_ts)
            .where(db.DailyStressSummary.summary_date < end_ts)
            # Prefer finalized rows for recap accuracy; fallback to latest partial row.
            .order_by(
                db.DailyStressSummary.is_partial_data.asc(),
                db.DailyStressSummary.summary_date.desc(),
            )
        )
        return result.scalars().first()

    async def _load_prior_boundaries(
        self, days: int = 14
    ) -> list[WakeSleepBoundary]:
        """
        Load historical DailyStressSummary rows and reconstruct WakeSleepBoundary
        objects for the wake_detector fallback chain.
        """
        cutoff = datetime.now(UTC) - timedelta(days=days)
        result = await self._db.execute(
            select(db.DailyStressSummary)
            .where(db.DailyStressSummary.user_id == self._uid)
            .where(db.DailyStressSummary.summary_date >= cutoff)
            .order_by(db.DailyStressSummary.summary_date.desc())
        )
        rows = result.scalars().all()
        boundaries: list[WakeSleepBoundary] = []
        for row in rows:
            if row.wake_ts and row.sleep_ts:
                boundaries.append(WakeSleepBoundary(
                    user_id    = str(row.user_id),
                    day_date   = row.summary_date.date() if row.summary_date else None,
                    wake_ts    = row.wake_ts,
                    sleep_ts   = row.sleep_ts,
                    wake_detection_method  = row.wake_detection_method or "unknown",
                    sleep_detection_method = row.sleep_detection_method or "unknown",
                    waking_minutes = row.waking_minutes or 0.0,
                ))
        return boundaries

    async def _count_days_with_data(self) -> int:
        # Use SQL COUNT(*) rather than loading every row into memory.
        from sqlalchemy import func as _func
        result = await self._db.execute(
            select(_func.count())
            .select_from(db.DailyStressSummary)
            .where(db.DailyStressSummary.user_id == self._uid)
            .where(db.DailyStressSummary.is_partial_data == False)  # noqa: E712
        )
        return int(result.scalar() or 0)

    @staticmethod
    def _db_stress_to_results(rows: Sequence[db.StressWindow]) -> list[StressWindowResult]:
        out = []
        for row in rows:
            out.append(StressWindowResult(
                user_id          = str(row.user_id),
                started_at       = row.started_at,
                ended_at         = row.ended_at,
                duration_minutes = row.duration_minutes,
                rmssd_min_ms     = row.rmssd_min_ms,
                suppression_pct  = row.suppression_pct,
                stress_contribution_pct = row.stress_contribution_pct,
                suppression_area        = row.suppression_area,
                tag          = row.tag,
                tag_candidate = row.tag_candidate,
                tag_source   = row.tag_source,
                nudge_sent   = row.nudge_sent,
                nudge_responded = row.nudge_responded,
            ))
        return out

    @staticmethod
    def _db_recovery_to_results(rows: Sequence[db.RecoveryWindow]) -> list[RecoveryWindowResult]:
        out = []
        for row in rows:
            out.append(RecoveryWindowResult(
                user_id          = str(row.user_id),
                started_at       = row.started_at,
                ended_at         = row.ended_at,
                duration_minutes = row.duration_minutes,
                context          = row.context,
                rmssd_avg_ms     = row.rmssd_avg_ms,
                recovery_contribution_pct = row.recovery_contribution_pct,
                recovery_area    = row.recovery_area,
                tag              = row.tag,
                tag_source       = row.tag_source,
                zenflow_session_id = str(row.zenflow_session_id) if row.zenflow_session_id else None,
            ))
        return out
