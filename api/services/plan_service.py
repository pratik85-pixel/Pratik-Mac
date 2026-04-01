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
import json
import re
import uuid
from datetime import date, datetime, timedelta, UTC
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.schema import (
    DailyPlan as DailyPlanRow,
    DailyStressSummary,
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
    build_daily_plan_from_uup,
    plan_to_items_json,
)
from api.services.profile_service import load_unified_profile
from tracking.cycle_boundaries import local_today
from tracking.plan_readiness_contract import (
    compute_composite_readiness,
    day_type_from_readiness,
    plan_api_contract_metadata,
)

logger = logging.getLogger(__name__)


class PlanService:
    """
    Stateless async service — instantiated per-request via FastAPI dependency.
    """

    def __init__(
        self,
        db: AsyncSession,
        model_service: ModelService,
        llm_client: Optional[Any] = None,
    ) -> None:
        self._db        = db
        self._model_svc = model_service
        self._llm_client = llm_client

    @staticmethod
    def empty_plan_payload() -> dict:
        """Payload when strict yesterday summary is missing (no valid plan for the day)."""
        return {
            "id":               None,
            "plan_date":        None,
            "day_type":         None,
            "readiness_score":  None,
            "stage":            None,
            "items":            [],
            "prescriber_notes": [],
            "adherence_pct":    None,
            "brief":            None,
            "avoid_items":     [],
            **plan_api_contract_metadata(),
        }

    @staticmethod
    def empty_home_plan_status() -> dict:
        """Same shape as get_home_plan_status when no plan exists."""
        return {
            "has_plan": False,
            "plan_date": None,
            "anchor_intention": None,
            "anchor_slug": None,
            "items_total": 0,
            "items_completed": 0,
            "adherence_pct": None,
            "on_track": None,
            "day_type": None,
        }

    async def delete_today_plan_if_exists(self, user_id: str) -> None:
        """Remove today's DailyPlan row so a stale plan cannot reappear after strict gating."""
        uid = parse_uuid(user_id)
        if uid is None:
            return
        today = local_today()
        today_dt = datetime(today.year, today.month, today.day, tzinfo=UTC)
        row = await self._load_today_row(uid, today_dt)
        if row is None:
            return
        await self._db.delete(row)
        await self._db.commit()
        logger.info("delete_today_plan_if_exists user=%s", user_id)

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
        today = local_today()
        today_dt = datetime(today.year, today.month, today.day, tzinfo=UTC)

        if uid is not None and not force_regen:
            existing = await self._load_today_row(uid, today_dt)
            if existing is not None:
                payload = self._row_to_dict(existing)
                # Read plan brief + avoid_items directly from the DB row so we
                # access plan_brief_text which is NOT on the UnifiedProfile dataclass.
                try:
                    import api.db.schema as _db_schema
                    uup_row_res = await self._db.execute(
                        select(_db_schema.UserUnifiedProfile).where(
                            _db_schema.UserUnifiedProfile.user_id == uid
                        )
                    )
                    uup_row = uup_row_res.scalar_one_or_none()
                    cached_brief = uup_row.plan_brief_text if uup_row else None
                    cached_avoid = (uup_row.avoid_items_json or []) if uup_row else []
                    narrative = uup_row.coach_narrative if uup_row else None

                    if cached_brief is None:
                        # plan_brief_text cleared (morning brief just regenerated).
                        # Trigger a fresh Layer 3 call so plan screen always shows
                        # activity-specific content, not the home-screen morning brief.
                        try:
                            brief_result = await self._maybe_add_layer3_plan_brief_and_donts(
                                user_id=user_id,
                                uid=uid,
                                payload_items=payload.get("items") or [],
                                payload_day_type=payload.get("day_type"),
                                narrative=narrative,
                            )
                            payload.update(brief_result)
                        except Exception as _e:
                            logger.warning("plan brief regen failed (cached path): %s", _e)
                            payload.setdefault("brief", None)
                            payload.setdefault("avoid_items", [])
                    else:
                        payload["brief"] = cached_brief
                        payload["avoid_items"] = cached_avoid
                except Exception as _e:
                    logger.warning("plan brief load failed: %s", _e)
                    payload.setdefault("brief", None)
                    payload.setdefault("avoid_items", [])
                return payload

        # Build inputs from profile + habits
        inputs = await self._build_inputs(user_id, today)

        # Try LLM plan first — nightly Layer 2 output from unified profile
        if uid is not None:
            uup = await load_unified_profile(self._db, uid)
            if uup is not None:
                uup_plan = build_daily_plan_from_uup(
                    uup,
                    readiness_score=inputs.readiness_score,
                    stage=inputs.stage,
                )
                if uup_plan is not None:
                    await self._persist_plan(uid, uup_plan, today_dt)
                    logger.info("plan_source=uup user=%s", user_id)
                    payload = {**uup_plan.model_dump(), **plan_api_contract_metadata()}
                    # Optional Layer 3: brief + donts from narrative
                    payload.update(
                        await self._maybe_add_layer3_plan_brief_and_donts(
                            user_id=user_id,
                            uid=uid,
                            payload_items=payload.get("items") or [],
                            payload_day_type=payload.get("day_type"),
                            narrative=uup.coach_narrative,
                        )
                    )
                    return payload

        # Fallback: rule-based prescriber
        plan: DailyPlan = build_daily_plan(inputs)

        if uid is not None:
            await self._persist_plan(uid, plan, today_dt)

        payload = {**plan.model_dump(), **plan_api_contract_metadata()}
        if uid is not None:
            try:
                uup = await load_unified_profile(self._db, uid)
                narrative = uup.coach_narrative if uup is not None else None
                payload.update(
                    await self._maybe_add_layer3_plan_brief_and_donts(
                        user_id=user_id,
                        uid=uid,
                        payload_items=payload.get("items") or [],
                        payload_day_type=payload.get("day_type"),
                        narrative=narrative,
                    )
                )
            except Exception:
                # Layer 3 is best-effort; never block plan fetch.
                pass

        return payload

    async def _maybe_add_layer3_plan_brief_and_donts(
        self,
        *,
        user_id: str,
        uid: uuid.UUID,
        payload_items: list[dict],
        payload_day_type: Optional[str],
        narrative: Optional[str],
    ) -> dict[str, Any]:
        """
        Best-effort Layer 3: generate plan brief + avoid_items from narrative.
        If LLM is disabled/unavailable or narrative missing, returns safe defaults.
        """
        if self._llm_client is None or not narrative:
            return {"brief": None, "avoid_items": []}

        try:
            from coach.input_builder import build_coach_input_packet
            from coach.prompt_templates import build_layer3_plan_brief_prompt

            packet = await build_coach_input_packet(self._db, uid)
            sys_prompt, user_prompt = build_layer3_plan_brief_prompt(
                packet=packet,
                uup_narrative=narrative,
                plan_items=payload_items,
            )
            raw = self._llm_client.chat(sys_prompt, user_prompt)

            # Parse JSON robustly.
            cleaned = raw.strip()
            cleaned = re.sub(r"^```(?:json)?\n?", "", cleaned)
            cleaned = re.sub(r"\n?```$", "", cleaned)
            m = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if not m:
                return {"brief": None, "avoid_items": []}
            obj = json.loads(m.group(0))

            brief = obj.get("brief")
            avoid_items = obj.get("avoid_items") or []

            # Shape/limit for safety.
            out_avoid: list[dict[str, Any]] = []
            for it in avoid_items[:2]:
                if not isinstance(it, dict):
                    continue
                slug_or_label = it.get("slug_or_label") or it.get("label")
                reason = it.get("reason")
                if not slug_or_label or not reason:
                    continue
                out_avoid.append(
                    {"slug_or_label": str(slug_or_label)[:100], "reason": str(reason)[:300]}
                )

            result = {"brief": str(brief)[:600] if brief is not None else None, "avoid_items": out_avoid}

            # Cache brief + avoid_items in UUP so the plan cache path can return them too.
            try:
                from sqlalchemy import select as _select
                import api.db.schema as _db
                uup_res = await self._db.execute(
                    _select(_db.UserUnifiedProfile).where(_db.UserUnifiedProfile.user_id == uid)
                )
                uup_row = uup_res.scalar_one_or_none()
                if uup_row is not None:
                    uup_row.plan_brief_text = result["brief"]
                    uup_row.avoid_items_json = out_avoid
                    await self._db.commit()
            except Exception as _cache_err:
                logger.warning("plan brief UUP cache write failed: %s", _cache_err)

            return result
        except Exception:
            return {"brief": None, "avoid_items": []}

    async def get_home_plan_status(self, user_id: str) -> dict:
        """
        Compact plan snapshot for Home (Phase 6): anchor intention + adherence + on_track.
        Calendar day uses IST to match get_or_create_today_plan.
        """
        uid = parse_uuid(user_id)
        empty = self.empty_home_plan_status()
        if uid is None:
            return empty

        today = local_today()
        today_dt = datetime(today.year, today.month, today.day, tzinfo=UTC)
        row = await self._load_today_row(uid, today_dt)
        if row is None:
            return empty

        d = self._row_to_dict(row)
        items = d.get("items") or []
        must_do = [i for i in items if i.get("priority") == "must_do"]
        anchor = must_do[0] if must_do else (items[0] if items else None)
        anchor_title = (anchor or {}).get("title") or None
        anchor_slug = (anchor or {}).get("activity_type_slug") or (anchor or {}).get("id") or None
        completed = sum(1 for i in items if i.get("has_evidence", False))
        total = len(items)
        adh = d.get("adherence_pct")
        on_track: Optional[bool] = None
        if total > 0:
            if adh is not None:
                on_track = adh >= 50.0
            else:
                on_track = completed >= max(1, total // 4)

        return {
            "has_plan": True,
            "plan_date": d.get("plan_date"),
            "anchor_intention": anchor_title,
            "anchor_slug": anchor_slug,
            "items_total": total,
            "items_completed": completed,
            "adherence_pct": adh,
            "on_track": on_track,
            "day_type": d.get("day_type"),
        }

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

        today = local_today()
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
        next_day_dt = today_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        from datetime import timedelta
        next_day_dt = next_day_dt + timedelta(days=1)
        result = await self._db.execute(
            select(DailyPlanRow)
            .where(
                DailyPlanRow.user_id == uid,
                DailyPlanRow.plan_date >= today_dt,
                DailyPlanRow.plan_date < next_day_dt,
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

        from coach.plan_replanner import compute_daily_prescription

        readiness = 50.0
        if uid is not None:
            today_dt = datetime(today.year, today.month, today.day, tzinfo=UTC)
            day_end = today_dt + timedelta(days=1)
            ds_res = await self._db.execute(
                select(DailyStressSummary).where(
                    DailyStressSummary.user_id == uid,
                    DailyStressSummary.summary_date >= today_dt,
                    DailyStressSummary.summary_date < day_end,
                )
            )
            t_row = ds_res.scalar_one_or_none()
            if t_row is not None and t_row.readiness_score is not None:
                readiness = float(t_row.readiness_score)
            else:
                y = today - timedelta(days=1)
                y_start = datetime(y.year, y.month, y.day, tzinfo=UTC)
                y_end = y_start + timedelta(days=1)
                y_res = await self._db.execute(
                    select(DailyStressSummary).where(
                        DailyStressSummary.user_id == uid,
                        DailyStressSummary.summary_date >= y_start,
                        DailyStressSummary.summary_date < y_end,
                    )
                )
                y_row = y_res.scalar_one_or_none()
                if y_row is not None:
                    cr = compute_composite_readiness(
                        y_row.waking_recovery_score,
                        getattr(y_row, "sleep_recovery_score", None),
                        float(y_row.stress_load_score) / 10.0
                        if y_row.stress_load_score is not None
                        else None,
                    )
                    if cr is not None:
                        readiness = cr

        prescription = compute_daily_prescription(profile, readiness_score=readiness)
        day_type = day_type_from_readiness(readiness)

        return PrescriberInputs(
            stage=profile.stage,
            archetype_primary=profile.primary_pattern,
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
        raw_items = row.items_json or []
        items = [
            {
                "id":                item.get("activity_type_slug") or item.get("activity_slug", ""),
                "category":          item.get("category", ""),
                "activity_type_slug": item.get("activity_type_slug") or item.get("activity_slug", ""),
                "title":             item.get("title") or item.get("display", ""),
                "target_start_time": item.get("target_start_time", None),
                "target_end_time":   item.get("target_end_time", None),
                "duration_minutes":  item.get("duration_minutes") or item.get("duration_min") or 0,
                "priority":          item.get("priority", "optional"),
                "rationale":         item.get("rationale") or item.get("reason_note") or item.get("reason_code", ""),
                "has_evidence":      bool(item.get("has_evidence", False)),
                "adherence_score":   item.get("adherence_score", None),
            }
            for item in raw_items
        ]
        return {
            "id":               str(row.id),
            "plan_date":        row.plan_date.date().isoformat() if row.plan_date else None,
            "day_type":         row.day_type,
            "readiness_score":  row.readiness_score,
            "stage":            row.stage,
            "items":            items,
            "prescriber_notes": row.prescriber_notes or [],
            "adherence_pct":    row.adherence_pct,
            **plan_api_contract_metadata(),
        }

    async def confirm_plan_item(self, user_id: str, tag: str) -> bool:
        """
        Runs IntradayMatcher using the confirmed tag.
        Updates the daily plan's items_json if an item matches.
        """
        from datetime import datetime, UTC
        from api.utils import parse_uuid
        from tagging.intraday_matcher import IntradayMatcher
        from sqlalchemy.orm.attributes import flag_modified
        
        uid = parse_uuid(user_id)
        if not uid: return False
        today = local_today()
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

    async def complete_plan_item(self, user_id: str, slug: str) -> bool:
        """
        Mark a plan item as complete by its activity slug.
        Sets has_evidence=True on the matching item in items_json,
        recalculates adherence_pct, and persists the change.
        Returns True if a matching item was found and updated.
        """
        from datetime import datetime, UTC
        from sqlalchemy.orm.attributes import flag_modified

        uid = parse_uuid(user_id)
        if not uid:
            return False

        today = local_today()
        today_dt = datetime(today.year, today.month, today.day, tzinfo=UTC)
        plan_row = await self._load_today_row(uid, today_dt)
        if not plan_row or not plan_row.items_json:
            return False

        items = plan_row.items_json
        matched = False
        for item in items:
            item_id = item.get("activity_type_slug") or item.get("activity_slug", "")
            if item_id == slug:
                item["has_evidence"] = True
                matched = True
                break

        if not matched:
            return False

        completed = sum(1 for i in items if i.get("has_evidence", False))
        total = len(items)
        plan_row.adherence_pct = round(completed / total * 100) if total > 0 else 0

        flag_modified(plan_row, "items_json")
        await self._db.commit()
        logger.info("complete_plan_item user=%s slug=%s adherence_pct=%s", user_id, slug, plan_row.adherence_pct)
        return True

