"""
api/services/model_service.py

CRUD operations for the personal physiological model.

Responsibilities
----------------
- Load and persist `PersonalFingerprint` from/to the database.
- Run `fingerprint_updater.run_update()` with new metric readings after a
  session ends.
- Build `NSHealthProfile` from the current fingerprint (used by coach service).
- Save archetype state back to `users` table after classifier runs.

DB pattern: accepts an `AsyncSession` dependency injected by FastAPI.
If `db` is None (unit tests / offline mode) returns sensible stubs.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, UTC
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from model.baseline_builder import PersonalFingerprint, MetricReading
from model.fingerprint_updater import run_update
from archetypes.scorer import compute_ns_health_profile, NSHealthProfile
from outcomes.session_outcomes import SessionOutcome
from api.db.schema import PersonalModel, User

logger = logging.getLogger(__name__)


def _parse_uuid(user_id: str) -> Optional[uuid.UUID]:
    """Return parsed UUID or None if user_id is not a valid UUID string."""
    try:
        return uuid.UUID(user_id)
    except (ValueError, AttributeError):
        return None


def _fingerprint_from_row(row: PersonalModel) -> PersonalFingerprint:
    """Reconstruct a PersonalFingerprint from an ORM row."""
    fp = PersonalFingerprint()
    fp.rmssd_floor              = row.rmssd_floor
    fp.rmssd_ceiling            = row.rmssd_ceiling
    fp.rmssd_morning_avg        = row.rmssd_morning_avg
    fp.recovery_arc_mean_hours  = row.recovery_arc_mean_hours
    fp.recovery_arc_fast_hours  = row.recovery_arc_fast_hours
    fp.recovery_arc_slow_hours  = row.recovery_arc_slow_hours
    fp.coherence_floor          = row.coherence_floor
    fp.coherence_trainability   = row.coherence_trainability
    fp.stress_peak_hour         = row.stress_peak_hour
    fp.best_natural_window_start = row.compliance_best_window
    fp.interoception_first_r    = row.interoception_gap
    fp.rsa_resting_avg          = row.rsa_resting_avg
    fp.rsa_guided_avg           = row.rsa_guided_avg
    fp.lf_hf_resting            = row.lf_hf_resting
    fp.lf_hf_sleep              = row.lf_hf_sleep
    # Additional fields stored in JSON blob
    if row.fingerprint_json:
        for k, v in row.fingerprint_json.items():
            if hasattr(fp, k):
                setattr(fp, k, v)
    return fp


def _fingerprint_to_dict(fp: PersonalFingerprint) -> dict:
    """Serialise only the fields not already in dedicated columns."""
    return {k: v for k, v in fp.__dict__.items() if v is not None}


class ModelService:

    def __init__(self, db: Optional[AsyncSession] = None) -> None:
        self._db = db

    # ── User ──────────────────────────────────────────────────────────────────

    async def get_user(self, user_id: str) -> Optional[User]:
        if self._db is None:
            return None
        uid = _parse_uuid(user_id)
        if uid is None:
            return None
        result = await self._db.execute(
            select(User).where(User.id == uid)
        )
        return result.scalar_one_or_none()

    # ── Fingerprint ───────────────────────────────────────────────────────────

    async def get_fingerprint(self, user_id: str) -> Optional[PersonalFingerprint]:
        if self._db is None:
            return PersonalFingerprint()  # empty baseline for offline/test mode

        uid = _parse_uuid(user_id)
        if uid is None:
            return PersonalFingerprint()  # non-UUID → offline fallback

        result = await self._db.execute(
            select(PersonalModel).where(PersonalModel.user_id == uid)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return PersonalFingerprint()
        return _fingerprint_from_row(row)

    async def get_profile(self, user_id: str) -> NSHealthProfile:
        """Return the NSHealthProfile computed from the current fingerprint."""
        fp = await self.get_fingerprint(user_id) or PersonalFingerprint()
        return self.get_profile_from_fingerprint(fp)

    @staticmethod
    def get_profile_from_fingerprint(fp: Optional[PersonalFingerprint]) -> NSHealthProfile:
        """Compute a profile from an already-loaded fingerprint (no DB read)."""
        return compute_ns_health_profile(fp or PersonalFingerprint())

    async def update_fingerprint_from_outcome(
        self,
        user_id:    str,
        outcome:    SessionOutcome,
        readings:   Optional[list[MetricReading]] = None,
    ) -> None:
        """
        Apply a new SessionOutcome to the stored fingerprint.
        If `readings` is not supplied, synthesises MetricReadings from the
        outcome's pre/post RMSSD values.

        Calibration lock (Phase 10): if the PersonalModel row already has
        calibration_locked_at set, the floor/ceiling/morning_avg freeze is
        enforced automatically via run_update(calibration_locked=True).
        """
        fp = await self.get_fingerprint(user_id) or PersonalFingerprint()

        # Determine calibration lock from persisted DB state
        calibration_locked = False
        if self._db is not None:
            uid = _parse_uuid(user_id)
            if uid is not None:
                _res = await self._db.execute(
                    select(PersonalModel).where(PersonalModel.user_id == uid)
                )
                _row = _res.scalar_one_or_none()
                if _row is not None and _row.calibration_locked_at is not None:
                    calibration_locked = True

        if readings is None:
            readings = []
            ts = datetime.now(UTC)
            if outcome.rmssd_pre_ms is not None:
                readings.append(MetricReading(
                    ts=ts, name="rmssd_ms",
                    value=outcome.rmssd_pre_ms, context="session",
                ))
            if outcome.rmssd_post_ms is not None:
                readings.append(MetricReading(
                    ts=ts, name="rmssd_ms",
                    value=outcome.rmssd_post_ms, context="session",
                ))

        if readings:
            run_update(fp, readings, calibration_locked=calibration_locked)

        await self._persist_fingerprint(user_id, fp)

    async def _persist_fingerprint(
        self, user_id: str, fp: PersonalFingerprint
    ) -> None:
        if self._db is None:
            return

        uid = _parse_uuid(user_id)
        if uid is None:
            return  # non-UUID user_id → skip persist

        result = await self._db.execute(
            select(PersonalModel).where(PersonalModel.user_id == uid)
        )
        row = result.scalar_one_or_none()

        if row is None:
            row = PersonalModel(user_id=uid)
            self._db.add(row)

        # rmssd_floor, rmssd_ceiling, rmssd_morning_avg are INTENTIONALLY NOT
        # written here. Those fields are owned exclusively by:
        #   - _run_calibration_batch() (floor, ceiling, morning_avg)
        #   - ingest_background_window() morning EWM update (morning_avg)
        # Writing them here would silently overwrite calibration results with
        # stale fingerprint values loaded before the batch committed.
        row.recovery_arc_mean_hours = fp.recovery_arc_mean_hours
        row.recovery_arc_fast_hours = fp.recovery_arc_fast_hours
        row.recovery_arc_slow_hours = fp.recovery_arc_slow_hours
        row.coherence_floor         = fp.coherence_floor
        row.coherence_trainability  = fp.coherence_trainability
        row.stress_peak_hour        = fp.stress_peak_hour
        row.compliance_best_window  = fp.best_natural_window_start
        row.interoception_gap       = fp.interoception_first_r
        row.rsa_resting_avg         = fp.rsa_resting_avg
        row.rsa_guided_avg          = fp.rsa_guided_avg
        row.lf_hf_resting           = fp.lf_hf_resting
        row.lf_hf_sleep             = fp.lf_hf_sleep
        row.fingerprint_json        = _fingerprint_to_dict(fp)
        row.version                 = (row.version or 0) + 1
        # calibration_locked_at is set externally by close_day(); don't touch here

        await self._db.commit()
        logger.debug("fingerprint persisted user=%s version=%d", user_id, row.version)
