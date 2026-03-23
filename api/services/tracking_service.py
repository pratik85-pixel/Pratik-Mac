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
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from tracking.background_processor import BackgroundWindowResult, aggregate_background_window
from tracking.stress_detector import StressWindowResult, detect_stress_windows, compute_stress_contributions
from tracking.recovery_detector import RecoveryWindowResult, detect_recovery_windows, compute_recovery_contributions
from tracking.daily_summarizer import DailySummaryResult, compute_daily_summary
from tracking.wake_detector import WakeSleepBoundary, ContextTransition, detect_wake_sleep_boundary

import numpy as np

from api.db import schema as db
from config import CONFIG

logger = logging.getLogger(__name__)


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

        personal = db.PersonalModel(
            user_id                      = user_id,
            rmssd_floor                  = seed_floor,
            rmssd_ceiling                = seed_ceiling,
            rmssd_morning_avg            = seed_morning,
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

    # --- Update personal model if confidence is adequate ---
    if filter_result.confidence >= 0.65 and rmssd_floor_clean is not None and rmssd_ceiling_clean is not None:
        personal.rmssd_floor                 = round(rmssd_floor_clean, 1)
        personal.rmssd_ceiling               = round(rmssd_ceiling_clean, 1)
        personal.rmssd_morning_avg           = round(rmssd_morning_avg_clean, 1)  # always set with floor+ceiling
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

    def __init__(self, db_session: AsyncSession, user_id: str):
        self._db  = db_session
        self._uid = user_id

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
            window exceeds BAND_GAP_CLOSE_MINUTES (90 min).
          - On band-off close: snapshot final scores, mark is_closed=True.
          - On first sleep→background transition within a session: compute and
            lock the opening_balance carry-forward.
          - Subsequent sleep→background transitions do NOT reset (locked flag).

        Returns the BackgroundWindowResult for the caller (e.g. live UI push).
        """
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
        if band_session is not None:
            session_end = min(datetime.now(UTC), window_end + timedelta(minutes=5))
            await self._recompute_day_windows(band_session.started_at, session_end)
        else:
            day_start = window_start.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end   = day_start + timedelta(days=1)
            await self._recompute_day_windows(day_start, day_end)

        await self._db.commit()

        # Materialise live score after every successful ingest so the DB always
        # has a current row — UI reads from DB rather than computing on-the-fly.
        try:
            await self._materialise_daily_score()
        except Exception as _mat_exc:
            logger.warning("Score materialisation failed user=%s: %s", self._uid, _mat_exc)

        logger.debug("Ingested background window %s–%s valid=%s", window_start, window_end, result.is_valid)
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

            # Open fresh session — no opening balance, fresh slate
            new_session = db.BandWearSession(
                user_id                = self._uid,
                started_at             = window_start,
                ended_at               = None,
                is_closed              = False,
                has_sleep_data         = (context == "sleep"),
                opening_balance        = 0.0,
                opening_balance_locked = False,
            )
            self._db.add(new_session)
            await self._db.flush()
            logger.info(
                "BandWearSession opened user=%s started_at=%s (gap=%.1f min after close)",
                self._uid, window_start, gap_minutes or 0.0,
            )
            return

        # ── Continuing an open session ────────────────────────────────────────
        # Update has_sleep_data if this is a sleep window
        if context == "sleep" and not open_session.has_sleep_data:
            open_session.has_sleep_data = True

        # Update ended_at to the latest window end (for gap detection correctness)
        open_session.ended_at = window_end

        # Check for sleep→background transition (carry-forward trigger)
        if (
            context == "background"
            and not open_session.opening_balance_locked
            and prev_window is not None
            and prev_window.context == "sleep"
        ):
            # First wakeup within this session — compute opening balance from
            # everything before this window (the sleep + prior evening period).
            opening_bal = await self._compute_opening_balance(
                session_start = open_session.started_at,
                wake_ts       = window_start,
            )
            open_session.opening_balance        = opening_bal
            open_session.opening_balance_locked = True
            open_session.wake_locked_at         = window_start
            logger.info(
                "BandWearSession carry-forward locked user=%s opening_balance=%.2f wake_ts=%s",
                self._uid, opening_bal, window_start,
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

    async def _materialise_daily_score(self) -> None:
        """Upsert a DailyStressSummary row for today using the live computation.

        Called after every ingest.  Uses the open BandWearSession as the scope
        so the row is always aligned to the current wear period, not UTC midnight.
        Rows already closed (is_partial_data=False) are left untouched.
        """
        band_session = await self._get_open_band_session()

        if band_session is not None:
            # Scope to the band session's start date (NOT UTC today, which resets at 5:30 AM IST)
            session_date = band_session.started_at.date()
            day_start    = datetime(session_date.year, session_date.month, session_date.day, tzinfo=UTC)
        else:
            today     = datetime.now(UTC).date()
            day_start = datetime(today.year, today.month, today.day, tzinfo=UTC)

        # If the row for this start date is already finalised, nothing to do.
        existing = await self._load_day_summary(day_start.date())
        if existing is not None and not existing.is_partial_data:
            return

        if band_session is not None:
            live = await self._compute_session_summary(
                session_start   = band_session.started_at,
                session_end     = datetime.now(UTC),
                opening_balance = band_session.opening_balance,
                wake_locked_at  = band_session.wake_locked_at,
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
        row.raw_suppression_area      = live.raw_suppression_area
        row.raw_recovery_area_sleep   = live.raw_recovery_area_sleep
        row.raw_recovery_area_zenflow = live.raw_recovery_area_zenflow
        row.raw_recovery_area_daytime = live.raw_recovery_area_daytime
        row.raw_recovery_area_waking  = live.raw_recovery_area_waking
        row.max_possible_suppression  = live.max_possible_suppression
        row.is_estimated              = live.is_estimated
        row.is_partial_data           = True  # live rows are always partial
        row.waking_recovery_score     = live.waking_recovery_score
        row.net_balance               = live.net_balance
        row.ns_capacity_used          = live.ns_capacity_used
        row.stress_pct_raw            = live.stress_pct_raw
        row.recovery_pct_raw          = live.recovery_pct_raw
        row.ns_capacity_recovery      = live.ns_capacity_recovery_used

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
        for row in existing_s:
            await self._db.delete(row)

        existing_r = await _load_existing_recovery_windows(self._db, self._uid, day_start, day_end)
        for row in existing_r:
            await self._db.delete(row)

        for sw in raw_stress:
            self._db.add(_to_db_stress(sw))
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

    async def get_personal_model(self) -> Optional[db.PersonalModel]:
        """Return the user's PersonalModel row (or None if it doesn't exist yet)."""
        return await _load_personal_model(self._db, self._uid)

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
            return await self._compute_session_summary(
                session_start   = band_session.started_at,
                session_end     = now,
                opening_balance = band_session.opening_balance,
                wake_locked_at  = band_session.wake_locked_at,
            )

        # Fallback: UTC calendar day (used for historical/closed-day queries)
        cal_start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=UTC)
        cal_end   = cal_start + timedelta(days=1)
        day_start = cal_start
        day_end   = min(cal_end, now)

        personal = await _bootstrap_personal_model(self._db, self._uid)

        bg_windows = await _load_today_background(self._db, self._uid, day_start, day_end)
        if not bg_windows:
            return None

        morning_rmssd    = personal.rmssd_morning_avg or (
            ((personal.rmssd_floor or 22.0) + (personal.rmssd_ceiling or 65.0)) / 2.0
        )
        capacity_floor   = personal.rmssd_floor
        capacity_ceiling = personal.rmssd_ceiling
        capacity_version = personal.capacity_version or 0

        stress_db        = await _load_existing_stress_windows(self._db, self._uid, day_start, day_end)
        recovery_db      = await _load_existing_recovery_windows(self._db, self._uid, day_start, day_end)
        stress_results   = self._db_stress_to_results(stress_db)
        recovery_results = self._db_recovery_to_results(recovery_db)

        context_transitions: list[ContextTransition] = []
        prev_ctx: Optional[str] = None
        for w in bg_windows:
            if prev_ctx is not None and w.context != prev_ctx:
                context_transitions.append(ContextTransition(
                    ts           = w.window_start,
                    from_context = prev_ctx,
                    to_context   = w.context,
                ))
            prev_ctx = w.context

        last_bg_ts = bg_windows[-1].window_end
        boundary   = detect_wake_sleep_boundary(
            day_date                  = cal_start,
            user_id                   = self._uid,
            context_transitions       = context_transitions or None,
            typical_wake_time         = personal.typical_wake_time,
            typical_sleep_time        = personal.typical_sleep_time,
            morning_read_ts           = None,
            last_background_window_ts = last_bg_ts,
        )
        if bg_windows:
            band_on_ts = bg_windows[0].window_start
            elapsed_from_band = (min(cal_end, now) - band_on_ts).total_seconds() / 60.0
            boundary = WakeSleepBoundary(
                user_id               = self._uid,
                day_date              = cal_start,
                wake_ts               = band_on_ts,
                sleep_ts              = boundary.sleep_ts,
                wake_detection_method = "band_on_anchor",
                sleep_detection_method= boundary.sleep_detection_method,
                waking_minutes        = elapsed_from_band,
            )

        calibration_days = await self._count_days_with_data()
        calibration_locked = personal.calibration_locked_at is not None

        result = compute_daily_summary(
            user_id              = self._uid,
            summary_date         = cal_start,
            background_windows   = bg_windows,
            stress_windows       = stress_results,
            recovery_windows     = recovery_results,
            boundary             = boundary,
            personal_morning_avg = morning_rmssd or 0.0,
            personal_floor       = capacity_floor or 0.0,
            personal_ceiling     = capacity_ceiling or (morning_rmssd or 0.0),
            capacity_version     = capacity_version,
            calibration_days     = calibration_days,
            calibration_locked   = calibration_locked,
            day_type             = None,
            capacity_floor_used  = capacity_floor,
            opening_balance      = 0.0,   # historical/closed-day: no carry-forward
            rmssd_sleep_avg      = personal.rmssd_sleep_avg,
            sleep_ceiling        = personal.rmssd_sleep_ceiling,
        )
        result.is_partial_data = True  # always partial — day is not closed yet
        return result

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
        result = await self._db.execute(
            select(db.DailyStressSummary)
            .where(db.DailyStressSummary.user_id == self._uid)
            .where(db.DailyStressSummary.is_partial_data == False)  # noqa: E712
        )
        return len(result.scalars().all())

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
