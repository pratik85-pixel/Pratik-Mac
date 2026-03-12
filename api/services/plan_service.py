"""
api/services/plan_service.py

Async SQLAlchemy wrapper around the daily plan generation and deviation
recording logic.

Responsibilities
----------------
- Build a DailyPlan using coach/prescriber.build_daily_plan()
- Persist the plan to the daily_plans table (one plan per user per day)
- Return today's plan (load from DB if already generated, else create)
- Record PlanDeviation rows when a user skips/misses a planned item
- Return deviation history for assessor / coach context

Dependencies
------------
- coach.prescriber (build_daily_plan, PrescriberInputs, plan_to_items_json)
- api.db.schema (DailyPlan as DailyPlanRow, PlanDeviation)
- api.services.model_service (ModelService)
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, UTC
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.schema import (
    DailyPlan as DailyPlanRow,
    PlanDeviation,
    UserHabits,
    HabitEvent,
)
from api.services.model_service import ModelService
from api.utils import parse_uuid
from coach.prescriber import (
    DailyPlan,
    PrescriberInputs,
    build_daily_plan,
    plan_to_items_json,
)

logger = logging.getLogger(__name__)


class PlanService:
    """
    Stateless async service — instantiated per-request via FastAPI dependency.
    """

    def __init__(self, db: AsyncSession, model_service: ModelService) -> None:
        self._db        = db
        self._model_svc = model_service

    # ── Today's plan ──────────────────────────────────────────────────────────

    async def get_or_create_today_plan(
        self,
        user_id: str,
        force_regen: bool = False,
    ) -> dict:
        """
        Return today's DailyPlan as a dict.

        If a plan already exists for today and `force_regen` is False,
        the cached row is returned.  Otherwise a new plan is generated
        and persisted (replacing any existing row for today).
        """
        uid = parse_uuid(user_id)
        today = date.today()
        today_dt = datetime(today.year, today.month, today.day, tzinfo=UTC)

        if uid is not None and not force_regen:
            existing = await self._load_today_row(uid, today_dt)
            if existing is not None:
                return self._row_to_dict(existing)

        # Build inputs from profile + habits
        inputs = await self._build_inputs(user_id, today)
        plan: DailyPlan = build_daily_plan(inputs)

        if uid is not None:
            await self._persist_plan(uid, plan, today_dt)

        return plan.model_dump()

    # ── Record deviation ──────────────────────────────────────────────────────

    async def record_deviation(
        self,
        user_id: str,
        activity_slug: str,
        priority: str,
        reason_category: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> str:
        """
        Record a PlanDeviation when a user skips or misses a planned item.
        Returns the deviation row id.
        """
        uid = parse_uuid(user_id)
        if uid is None:
            return ""

        today = date.today()
        today_dt = datetime(today.year, today.month, today.day, tzinfo=UTC)
        plan_row = await self._load_today_row(uid, today_dt)
        plan_id = plan_row.id if plan_row is not None else uuid.uuid4()

        row = PlanDeviation(
            user_id=uid,
            plan_id=plan_id,
            activity_slug=activity_slug,
            priority=priority,
            reason_category=reason_category,
            notes=notes,
        )
        self._db.add(row)
        await self._db.commit()

        logger.info(
            "plan_deviation user=%s slug=%s priority=%s reason=%s",
            user_id, activity_slug, priority, reason_category,
        )
        return str(row.id)

    # ── Deviation history ─────────────────────────────────────────────────────

    async def get_deviation_history(
        self,
        user_id: str,
        limit: int = 20,
    ) -> list[dict]:
        """Return recent PlanDeviation rows for assessor / coach context."""
        uid = parse_uuid(user_id)
        if uid is None:
            return []

        result = await self._db.execute(
            select(PlanDeviation)
            .where(PlanDeviation.user_id == uid)
            .order_by(PlanDeviation.ts.desc())
            .limit(limit)
        )
        rows = list(result.scalars().all())
        return [
            {
                "id":              str(r.id),
                "activity_slug":   r.activity_slug,
                "priority":        r.priority,
                "reason_category": r.reason_category,
                "notes":           r.notes,
                "ts":              r.ts.isoformat() if r.ts else None,
            }
            for r in rows
        ]

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _load_today_row(
        self,
        uid: uuid.UUID,
        today_dt: datetime,
    ) -> Optional[DailyPlanRow]:
        result = await self._db.execute(
            select(DailyPlanRow)
            .where(
                DailyPlanRow.user_id == uid,
                DailyPlanRow.plan_date >= today_dt,
            )
            .order_by(DailyPlanRow.generated_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _persist_plan(
        self,
        uid: uuid.UUID,
        plan: DailyPlan,
        today_dt: datetime,
    ) -> DailyPlanRow:
        # Remove stale row for today if force_regen caused a rebuild
        stale = await self._load_today_row(uid, today_dt)
        if stale is not None:
            await self._db.delete(stale)

        all_items = plan.must_do + plan.recommended + plan.optional
        items_json = plan_to_items_json(plan)

        row = DailyPlanRow(
            user_id=uid,
            plan_date=today_dt,
            day_type=plan.day_type,
            readiness_score=plan.readiness,
            stage=plan.stage,
            items_json=items_json,
            prescriber_notes=plan.prescriber_notes,
        )
        self._db.add(row)
        await self._db.commit()
        await self._db.refresh(row)
        return row

    async def _build_inputs(
        self,
        user_id: str,
        today: date,
    ) -> PrescriberInputs:
        """
        Assemble PrescriberInputs from the user's profile, habits, and
        recent history stored in DB.

        Uses ModelService for fingerprint + profile.
        Fills remaining fields with safe defaults when data is unavailable.
        """
        profile = await self._model_svc.get_profile(user_id)
        fp      = await self._model_svc.get_fingerprint(user_id)

        uid = parse_uuid(user_id)

        # Pull UserHabits
        movement_enjoyed: list[str] = []
        decompress_via:   list[str] = []
        prf_status:       Optional[str] = None

        if uid is not None:
            habits_res = await self._db.execute(
                select(UserHabits).where(UserHabits.user_id == uid)
            )
            habits: Optional[UserHabits] = habits_res.scalar_one_or_none()
            if habits is not None:
                movement_enjoyed = habits.movement_enjoyed or []
                decompress_via   = habits.decompress_via or []

        # Pull recent HabitEvents (72 h)
        habit_labels_72h: list[str] = []
        if uid is not None:
            from datetime import timedelta
            cutoff = datetime.now(UTC) - timedelta(hours=72)
            he_res = await self._db.execute(
                select(HabitEvent)
                .where(
                    HabitEvent.user_id == uid,
                    HabitEvent.ts >= cutoff,
                )
                .order_by(HabitEvent.ts.desc())
                .limit(30)
            )
            habit_labels_72h = [r.event_type for r in he_res.scalars().all()]

        # Archetype + readiness via plan_replanner (consistent with /plan/today)
        from archetypes.scorer import compute_ns_health_profile
        from coach.plan_replanner import compute_daily_prescription
        from model.baseline_builder import PersonalFingerprint
        fp_obj = fp if fp is not None else PersonalFingerprint()
        ns_profile = compute_ns_health_profile(fp_obj)
        prescription = compute_daily_prescription(profile)

        # Map load_score (0–1, higher = more stressed) → readiness (0–100)
        readiness = round((1.0 - min(prescription.load_score, 1.0)) * 100, 1)

        # Day type from load_score
        if prescription.load_score < 0.35:
            day_type = "green"
        elif prescription.load_score < 0.65:
            day_type = "yellow"
        else:
            day_type = "red"

        return PrescriberInputs(
            stage=profile.stage,
            archetype_primary=ns_profile.primary_pattern,
            movement_enjoyed=movement_enjoyed,
            decompress_via=decompress_via,
            readiness_score=readiness,
            day_type=day_type,
            prf_status=prf_status,
            plan_date=today.isoformat(),
            day_of_week=today.weekday(),
            habit_events_72h=habit_labels_72h,
        )

    @staticmethod
    def _row_to_dict(row: DailyPlanRow) -> dict:
        return {
            "plan_id":          str(row.id),
            "plan_date":        row.plan_date.date().isoformat() if row.plan_date else None,
            "day_type":         row.day_type,
            "readiness_score":  row.readiness_score,
            "stage":            row.stage,
            "items":            row.items_json or [],
            "prescriber_notes": row.prescriber_notes or [],
            "adherence_pct":    row.adherence_pct,
        }

    async def confirm_plan_item(self, user_id: str, tag: str) -> bool:
        """
        Runs IntradayMatcher using the confirmed tag.
        Updates the daily plan's items_json if an item matches.
        """
        from datetime import date, datetime, UTC
        from api.utils import parse_uuid
        from tagging.intraday_matcher import IntradayMatcher
        from sqlalchemy.orm.attributes import flag_modified
        
        uid = parse_uuid(user_id)
        if not uid: return False
        today = date.today()
        today_dt = datetime(today.year, today.month, today.day, tzinfo=UTC)
        plan_row = await self._load_today_row(uid, today_dt)
        if not plan_row or not plan_row.items_json:
            return False
            
        matcher = IntradayMatcher()
        matched = matcher.match(plan_row.items_json, tag)
        if matched:
            flag_modified(plan_row, "items_json")
            await self._db.commit()
            return True
        return False

