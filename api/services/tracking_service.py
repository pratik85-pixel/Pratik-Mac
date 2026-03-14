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
from tracking.wake_detector import WakeSleepBoundary, detect_wake_sleep_boundary

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

# Population-average seeds (conservative HRV reference values)
_SEED_RMSSD_FLOOR    = 28.0   # ms  — 10th-pct adult resting
_SEED_RMSSD_CEILING  = 75.0   # ms  — 90th-pct adult resting
_SEED_RMSSD_MORNING  = 45.0   # ms  — median adult morning
_SEED_CAPACITY_FLOOR = 32.0   # ms  — seed stress detection threshold
_MIN_WINDOWS_FOR_REFINE = 3   # need ≥3 valid 5-min windows before refining


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

    If no row exists: create one with conservative population-average seed
    values so the detection pipeline can run immediately on first wear.

    While still in bootstrap phase (capacity_version == 0): refine the seed
    values with actual observed RMSSD statistics from BackgroundWindow rows
    whenever ≥ 3 valid windows are available.

    Once capacity_version > 0 (set by fingerprint_updater after proper
    calibration), this function leaves the model untouched.
    """
    personal = await _load_personal_model(db_session, user_id)
    is_new   = personal is None

    if is_new:
        personal = db.PersonalModel(
            user_id                      = user_id,
            rmssd_floor                  = _SEED_RMSSD_FLOOR,
            rmssd_ceiling                = _SEED_RMSSD_CEILING,
            rmssd_morning_avg            = _SEED_RMSSD_MORNING,
            stress_capacity_floor_rmssd  = _SEED_CAPACITY_FLOOR,
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
            is_new = False
        else:
            logger.info("Seeded population-average PersonalModel for user %s", user_id)

    # Refine from real data while still in bootstrap phase
    if (personal.capacity_version or 0) == 0:
        windows = await _load_all_background_for_model(db_session, user_id)
        rmssd_values = [
            w.rmssd_ms for w in windows
            if w.rmssd_ms is not None and w.rmssd_ms > 10.0
        ]
        if len(rmssd_values) >= _MIN_WINDOWS_FOR_REFINE:
            arr       = np.array(rmssd_values, dtype=float)
            floor     = float(np.percentile(arr, 10))
            ceiling   = float(np.percentile(arr, 90))
            morning   = float(np.median(arr))
            cap_floor = max(floor + 0.1 * (ceiling - floor), 20.0)

            personal.rmssd_floor                = round(floor,   1)
            personal.rmssd_ceiling              = round(ceiling, 1)
            personal.rmssd_morning_avg          = round(morning, 1)
            personal.stress_capacity_floor_rmssd= round(cap_floor, 1)
            await db_session.flush()
            logger.debug(
                "Bootstrap PersonalModel user=%s floor=%.1f ceiling=%.1f "
                "morning=%.1f n_windows=%d",
                user_id, floor, ceiling, morning, len(rmssd_values),
            )

    return personal


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

        # Persist raw window
        row = _to_db_background(result)
        self._db.add(row)
        await self._db.flush()   # get the id without committing

        # Recompute today's stress + recovery windows
        day_start = window_start.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end   = day_start + timedelta(days=1)
        await self._recompute_day_windows(day_start, day_end)

        await self._db.commit()
        logger.debug("Ingested background window %s–%s valid=%s", window_start, window_end, result.is_valid)
        return result

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

        morning_rmssd  = personal.rmssd_morning_avg
        capacity_floor = personal.stress_capacity_floor_rmssd or personal.rmssd_floor
        if capacity_floor is None or morning_rmssd is None:
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

    # ── Day close ──────────────────────────────────────────────────────────────

    async def close_day(self, target_date: date) -> DailySummaryResult:
        """
        Finalize the DailyStressSummary for `target_date`. Called once per day
        after the wake/sleep boundary is confirmed (or midnight fallback).

        1. Detect wake/sleep boundary from today's BackgroundWindows.
        2. Update PersonalModel.typical_wake/sleep timestamps.
        3. Run full daily_summarizer.
        4. Upsert DailyStressSummary row.
        5. Return result to caller.
        """
        day_start = datetime(
            target_date.year, target_date.month, target_date.day,
            tzinfo=UTC
        )
        day_end = day_start + timedelta(days=1)

        personal = await _bootstrap_personal_model(self._db, self._uid)

        morning_rmssd    = personal.rmssd_morning_avg
        capacity_floor   = personal.stress_capacity_floor_rmssd or personal.rmssd_floor
        capacity_ceiling = personal.rmssd_ceiling
        capacity_version = personal.capacity_version or 0

        bg_windows = await _load_today_background(self._db, self._uid, day_start, day_end)
        if not bg_windows:
            logger.warning("close_day: no background windows for %s user=%s", target_date, self._uid)

        # Wake/sleep boundary — derive from PersonalModel typical times
        last_bg_ts = bg_windows[-1].window_end if bg_windows else None
        boundary = detect_wake_sleep_boundary(
            day_date              = day_start,
            user_id               = self._uid,
            typical_wake_time     = personal.typical_wake_time,
            typical_sleep_time    = personal.typical_sleep_time,
            last_background_window_ts = last_bg_ts,
        )

        # Update PersonalModel typical times if boundary from sleep_transition
        typical_wake  = personal.typical_wake_time
        typical_sleep = personal.typical_sleep_time
        if boundary.wake_detection_method == "sleep_transition" and boundary.wake_ts:
            typical_wake = boundary.wake_ts.strftime("%H:%M")
        if boundary.sleep_detection_method == "sleep_transition" and boundary.sleep_ts:
            typical_sleep = boundary.sleep_ts.strftime("%H:%M")
        if typical_wake != personal.typical_wake_time or typical_sleep != personal.typical_sleep_time:
            personal.typical_wake_time  = typical_wake
            personal.typical_sleep_time = typical_sleep
            await self._db.flush()

        # Reload stress/recovery windows (final pass)
        stress_db  = await _load_existing_stress_windows(self._db, self._uid, day_start, day_end)
        recovery_db = await _load_existing_recovery_windows(self._db, self._uid, day_start, day_end)

        stress_results   = self._db_stress_to_results(stress_db)
        recovery_results = self._db_recovery_to_results(recovery_db)

        # Count calibration days
        calibration_days = await self._count_days_with_data()

        # ── Phase 10: continuous balance thread ───────────────────────────────
        # Fetch previous day's closing_balance for carry-forward.
        prev_date    = target_date - timedelta(days=1)
        prev_summary = await self._load_day_summary(prev_date)
        opening_balance = float(prev_summary.closing_balance or 0.0) if prev_summary else 0.0

        # Determine + persist calibration lock
        calibration_locked = calibration_days >= CONFIG.model.BASELINE_STABLE_DAYS
        if calibration_locked and personal.calibration_locked_at is None:
            from datetime import timezone
            personal.calibration_locked_at = datetime.now(timezone.utc)
            await self._db.flush()
            logger.info("Calibration locked for user %s after %d days", self._uid, calibration_days)
        # ─────────────────────────────────────────────────────────────────────

        result = compute_daily_summary(
            user_id              = self._uid,
            summary_date         = day_start,
            background_windows   = bg_windows,
            stress_windows       = stress_results,
            recovery_windows     = recovery_results,
            boundary             = boundary,
            personal_morning_avg = morning_rmssd or 0.0,
            personal_floor       = capacity_floor or 0.0,
            personal_ceiling     = capacity_ceiling or (morning_rmssd or 0.0),
            capacity_version     = capacity_version,
            calibration_days     = calibration_days,
            capacity_floor_used  = capacity_floor,
            opening_balance      = opening_balance,
        )
        existing_summary = await self._load_day_summary(target_date)
        if existing_summary is None:
            row = db.DailyStressSummary(
                user_id      = self._uid,
                summary_date = day_start,
            )
            self._db.add(row)
        else:
            row = existing_summary

        # Top window FKs
        top_stress_id   = None
        if stress_db:
            top = max(stress_db, key=lambda s: s.suppression_area or 0.0)
            top_stress_id = top.id

        top_recovery_id = None
        if recovery_db:
            top = max(recovery_db, key=lambda r: r.recovery_area or 0.0)
            top_recovery_id = top.id

        row.wake_ts                    = boundary.wake_ts
        row.sleep_ts                   = boundary.sleep_ts
        row.wake_detection_method      = boundary.wake_detection_method
        row.sleep_detection_method     = boundary.sleep_detection_method
        row.waking_minutes             = boundary.waking_minutes
        row.stress_load_score          = result.stress_load_score
        row.recovery_score             = result.recovery_score
        row.readiness_score            = result.readiness_score
        row.day_type                   = result.day_type
        row.raw_suppression_area       = result.raw_suppression_area
        row.raw_recovery_area_sleep    = result.raw_recovery_area_sleep
        row.raw_recovery_area_zenflow  = result.raw_recovery_area_zenflow
        row.raw_recovery_area_daytime  = result.raw_recovery_area_daytime
        row.raw_recovery_area_waking   = result.raw_recovery_area_waking
        row.max_possible_suppression   = result.max_possible_suppression
        row.capacity_floor_used        = capacity_floor
        row.capacity_version           = capacity_version
        row.calibration_days           = calibration_days
        row.is_estimated               = result.is_estimated
        row.is_partial_data            = result.is_partial_data
        row.top_stress_window_id       = top_stress_id
        row.top_recovery_window_id     = top_recovery_id
        row.waking_recovery_score      = result.waking_recovery_score
        row.net_balance                = result.net_balance
        # Phase 10: continuous balance + raw percentage fields
        row.opening_balance            = opening_balance
        row.closing_balance            = result.closing_balance
        row.ns_capacity_used           = result.ns_capacity_used
        row.stress_pct_raw             = result.stress_pct_raw
        row.recovery_pct_raw           = result.recovery_pct_raw

        await self._db.commit()
        logger.info("Closed day %s for user %s: readiness=%.0f day_type=%s",
                    target_date, self._uid, result.readiness_score or 0, result.day_type)

        # Wire evening assessor 
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
            logger.warning("Failed evening plan assessment: %s", e)

        return result

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

    async def compute_live_summary(
        self, target_date: date
    ) -> Optional[DailySummaryResult]:
        """
        Compute the three scores on-the-fly from today's existing intraday windows
        WITHOUT writing anything to the database.

        Returns None if there are no background windows yet (band not worn).
        Always marks is_partial_data=True since the day is not finalized.
        """
        day_start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=UTC)
        day_end   = day_start + timedelta(days=1)

        bg_windows = await _load_today_background(self._db, self._uid, day_start, day_end)
        if not bg_windows:
            return None

        personal         = await _bootstrap_personal_model(self._db, self._uid)
        morning_rmssd    = personal.rmssd_morning_avg
        capacity_floor   = personal.stress_capacity_floor_rmssd or personal.rmssd_floor
        capacity_ceiling = personal.rmssd_ceiling
        capacity_version = personal.capacity_version or 0

        # Use already-detected intraday windows (kept fresh by ingest_background_window)
        stress_db        = await _load_existing_stress_windows(self._db, self._uid, day_start, day_end)
        recovery_db      = await _load_existing_recovery_windows(self._db, self._uid, day_start, day_end)
        stress_results   = self._db_stress_to_results(stress_db)
        recovery_results = self._db_recovery_to_results(recovery_db)

        last_bg_ts = bg_windows[-1].window_end
        boundary   = detect_wake_sleep_boundary(
            day_date                  = day_start,
            user_id                   = self._uid,
            typical_wake_time         = personal.typical_wake_time,
            typical_sleep_time        = personal.typical_sleep_time,
            last_background_window_ts = last_bg_ts,
        )

        calibration_days = await self._count_days_with_data()

        # Fetch today's opening balance for accurate live net_balance display
        prev_date    = target_date - timedelta(days=1)
        prev_summary = await self._load_day_summary(prev_date)
        opening_balance = float(prev_summary.closing_balance or 0.0) if prev_summary else 0.0

        result = compute_daily_summary(
            user_id              = self._uid,
            summary_date         = day_start,
            background_windows   = bg_windows,
            stress_windows       = stress_results,
            recovery_windows     = recovery_results,
            boundary             = boundary,
            personal_morning_avg = morning_rmssd or 0.0,
            personal_floor       = capacity_floor or 0.0,
            personal_ceiling     = capacity_ceiling or (morning_rmssd or 0.0),
            capacity_version     = capacity_version,
            calibration_days     = calibration_days,
            capacity_floor_used  = capacity_floor,
            opening_balance      = opening_balance,
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
