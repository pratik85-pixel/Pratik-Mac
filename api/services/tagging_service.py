"""
api/services/tagging_service.py

Async SQLAlchemy wrapper around the pure tagging business logic in
tagging/tagging_service.py.

Responsibilities
----------------
- Load StressWindow / RecoveryWindow rows from DB → convert to WindowRef
- Load / persist TagPatternModel rows
- Run auto-tagger pass and persist changes
- Apply user-confirmed tags and persist
- Expose helper to build the nudge queue for a user
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, UTC
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.schema import (
    StressWindow,
    RecoveryWindow,
    TagPatternModel as TagPatternModelRow,
)
from api.utils import parse_uuid
from tagging.tag_pattern_model import UserTagPatternModel
from tagging.tagging_service import (
    AutoTagPassResult as AutoTagPass,
    PatternModelBuildResult,
    TagResult,
    WindowRef,
    apply_user_tag,
    build_pattern_model_from_windows,
    get_nudge_queue,
    run_auto_tag_pass,
    update_model_after_confirmation,
)

logger = logging.getLogger(__name__)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _stress_row_to_ref(row: StressWindow) -> WindowRef:
    return WindowRef(
        window_id=str(row.id),
        window_type="stress",
        started_at=row.started_at,
        tag=row.tag,
        tag_source=row.tag_source,
        suppression_pct=row.suppression_pct,
    )


def _recovery_row_to_ref(row: RecoveryWindow) -> WindowRef:
    return WindowRef(
        window_id=str(row.id),
        window_type="recovery",
        started_at=row.started_at,
        tag=row.tag,
        tag_source=row.tag_source,
        suppression_pct=None,
    )


# ── Service class ─────────────────────────────────────────────────────────────


class TaggingService:
    """
    Stateless async service — one instance per request via dependency injection.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # ── Pattern model loading / saving ─────────────────────────────────────────

    async def load_pattern_model(self, user_id: str) -> Optional[UserTagPatternModel]:
        """
        Load the user's TagPatternModel from DB.
        Returns None if no model row exists yet.
        """
        uid = parse_uuid(user_id)
        if uid is None:
            return None

        result = await self._db.execute(
            select(TagPatternModelRow).where(TagPatternModelRow.user_id == uid)
        )
        row: Optional[TagPatternModelRow] = result.scalar_one_or_none()
        if row is None:
            return None

        return UserTagPatternModel.from_dict(row.model_json or {})

    async def save_pattern_model(
        self,
        user_id: str,
        model: UserTagPatternModel,
        patterns_built: int,
        sport_stressor_slugs: list[str],
    ) -> None:
        """Upsert the TagPatternModel row for this user."""
        uid = parse_uuid(user_id)
        if uid is None:
            return

        result = await self._db.execute(
            select(TagPatternModelRow).where(TagPatternModelRow.user_id == uid)
        )
        row: Optional[TagPatternModelRow] = result.scalar_one_or_none()

        model_dict = model.to_dict()
        if row is None:
            row = TagPatternModelRow(
                user_id=uid,
                model_json=model_dict,
                patterns_built=patterns_built,
                sport_stressor_slugs=sport_stressor_slugs,
                version=1,
            )
            self._db.add(row)
        else:
            row.model_json = model_dict
            row.patterns_built = patterns_built
            row.sport_stressor_slugs = sport_stressor_slugs
            row.version = (row.version or 1) + 1
            row.updated_at = datetime.now(UTC)

        await self._db.commit()

    # ── Tag a window ───────────────────────────────────────────────────────────

    async def tag_window(
        self,
        user_id: str,
        window_id: str,
        window_type: str,
        slug: str,
    ) -> TagResult:
        """
        Apply a user-confirmed tag to a stress or recovery window.
        Updates the DB row and incrementally refreshes the pattern model.
        """
        w_uuid = parse_uuid(window_id)
        if w_uuid is None:
            return TagResult(
                success=False,
                window_id=window_id,
                tag_applied=None,
                tag_source="user_confirmed",
                error="Invalid window_id UUID.",
            )

        if window_type == "stress":
            result = await self._db.execute(
                select(StressWindow).where(StressWindow.id == w_uuid)
            )
            row: Optional[StressWindow] = result.scalar_one_or_none()
            if row is None:
                return TagResult(
                    success=False,
                    window_id=window_id,
                    tag_applied=None,
                    tag_source="user_confirmed",
                    error="StressWindow not found.",
                )
            ref = _stress_row_to_ref(row)
            tag_result = apply_user_tag(ref, slug)
            if tag_result.success:
                row.tag = slug
                row.tag_source = "user_confirmed"
                row.nudge_responded = True
        else:  # recovery
            r_result = await self._db.execute(
                select(RecoveryWindow).where(RecoveryWindow.id == w_uuid)
            )
            rec_row: Optional[RecoveryWindow] = r_result.scalar_one_or_none()
            if rec_row is None:
                return TagResult(
                    success=False,
                    window_id=window_id,
                    tag_applied=None,
                    tag_source="user_confirmed",
                    error="RecoveryWindow not found.",
                )
            ref = _recovery_row_to_ref(rec_row)
            tag_result = apply_user_tag(ref, slug)
            if tag_result.success:
                rec_row.tag = slug
                rec_row.tag_source = "user_confirmed"

        if tag_result.success:
            await self._db.commit()
            # Incremental pattern model refresh
            existing_model = await self.load_pattern_model(user_id)
            if existing_model is not None:
                # Mark window as confirmed for model update
                ref.tag = slug
                ref.tag_source = "user_confirmed"
                updated_model = update_model_after_confirmation(existing_model, ref)
                await self.save_pattern_model(
                    user_id=user_id,
                    model=updated_model,
                    patterns_built=len(updated_model.patterns),
                    sport_stressor_slugs=updated_model.sport_stressor_slugs,
                )

        logger.info(
            "tag_window user=%s window=%s type=%s slug=%s ok=%s",
            user_id, window_id, window_type, slug, tag_result.success,
        )

        # Ensure we commit the row tag update before calling plan service
        await self._db.commit()
        # Wire intraday plan adherence
        try:
            from api.services.plan_service import PlanService
            plan_svc = PlanService(self._db, None)
            await plan_svc.confirm_plan_item(user_id, slug)
        except Exception:
            pass 

        return tag_result

    # ── Auto-tag pass ──────────────────────────────────────────────────────────

    async def run_auto_tag_pass(
        self,
        user_id: str,
        since: Optional[datetime] = None,
    ) -> AutoTagPass:
        """
        Run the auto-tagger across all untagged windows for this user.
        Persists eligible auto-tags to DB.
        """
        uid = parse_uuid(user_id)
        if uid is None:
            return AutoTagPass(tagged_count=0, skipped_count=0, results=[])

        user_model = await self.load_pattern_model(user_id)
        if user_model is None:
            return AutoTagPass(tagged_count=0, skipped_count=0, results=[])

        # Load untagged stress windows
        stress_q = select(StressWindow).where(
            StressWindow.user_id == uid,
            StressWindow.tag == None,  # noqa: E711
        )
        if since:
            stress_q = stress_q.where(StressWindow.started_at >= since)
        stress_res = await self._db.execute(stress_q)
        stress_rows = list(stress_res.scalars().all())

        # Load untagged recovery windows (skip sleep / session auto-confirmed)
        rec_q = select(RecoveryWindow).where(
            RecoveryWindow.user_id == uid,
            RecoveryWindow.tag == None,  # noqa: E711
            RecoveryWindow.context == "background",
        )
        if since:
            rec_q = rec_q.where(RecoveryWindow.started_at >= since)
        rec_res = await self._db.execute(rec_q)
        rec_rows = list(rec_res.scalars().all())

        untagged_refs: list[WindowRef] = (
            [_stress_row_to_ref(r) for r in stress_rows]
            + [_recovery_row_to_ref(r) for r in rec_rows]
        )

        pass_result = run_auto_tag_pass(user_model, untagged_refs)

        # Persist eligible auto-tags
        eligible_map = {
            wid: suggestion
            for wid, suggestion in pass_result.results
            if suggestion.eligible
        }

        stress_id_map = {str(r.id): r for r in stress_rows}
        rec_id_map = {str(r.id): r for r in rec_rows}

        for wid, suggestion in eligible_map.items():
            if wid in stress_id_map:
                stress_id_map[wid].tag = suggestion.best_tag
                stress_id_map[wid].tag_source = "auto_tagged"
            elif wid in rec_id_map:
                rec_id_map[wid].tag = suggestion.best_tag
                rec_id_map[wid].tag_source = "auto_tagged"

        if eligible_map:
            await self._db.commit()

        logger.info(
            "auto_tag_pass user=%s tagged=%d skipped=%d",
            user_id, pass_result.tagged_count, pass_result.skipped_count,
        )
        return pass_result

    # ── Pattern model rebuild ─────────────────────────────────────────────────

    async def rebuild_pattern_model(self, user_id: str) -> PatternModelBuildResult:
        """
        Full rebuild of the user's pattern model from all confirmed windows.
        Written back to DB.
        """
        uid = parse_uuid(user_id)
        if uid is None:
            result = build_pattern_model_from_windows(user_id, [], [])
            return result

        # Confirmed stress windows
        s_res = await self._db.execute(
            select(StressWindow).where(
                StressWindow.user_id == uid,
                StressWindow.tag != None,  # noqa: E711
                StressWindow.tag_source.in_(["user_confirmed", "auto_tagged"]),
            )
        )
        stress_rows = list(s_res.scalars().all())

        # Confirmed recovery windows
        r_res = await self._db.execute(
            select(RecoveryWindow).where(
                RecoveryWindow.user_id == uid,
                RecoveryWindow.tag != None,  # noqa: E711
            )
        )
        rec_rows = list(r_res.scalars().all())

        stress_refs = [_stress_row_to_ref(r) for r in stress_rows]
        rec_refs = [_recovery_row_to_ref(r) for r in rec_rows]

        build_result = build_pattern_model_from_windows(user_id, stress_refs, rec_refs)

        await self.save_pattern_model(
            user_id=user_id,
            model=build_result.model,
            patterns_built=build_result.patterns_built,
            sport_stressor_slugs=build_result.sport_stressors,
        )

        return build_result

    # ── Nudge queue ───────────────────────────────────────────────────────────

    async def get_nudge_queue(
        self,
        user_id: str,
        max_items: int = 3,
        since: Optional[datetime] = None,
    ) -> list[WindowRef]:
        """
        Return up to `max_items` untagged windows for the Tag Sheet nudge UI.
        """
        uid = parse_uuid(user_id)
        if uid is None:
            return []

        stress_q = select(StressWindow).where(
            StressWindow.user_id == uid,
            StressWindow.tag == None,  # noqa: E711
        )
        if since:
            stress_q = stress_q.where(StressWindow.started_at >= since)
        stress_res = await self._db.execute(stress_q)
        stress_rows = list(stress_res.scalars().all())

        rec_q = select(RecoveryWindow).where(
            RecoveryWindow.user_id == uid,
            RecoveryWindow.tag == None,  # noqa: E711
            RecoveryWindow.context == "background",
        )
        if since:
            rec_q = rec_q.where(RecoveryWindow.started_at >= since)
        rec_res = await self._db.execute(rec_q)
        rec_rows = list(rec_res.scalars().all())

        all_refs: list[WindowRef] = (
            [_stress_row_to_ref(r) for r in stress_rows]
            + [_recovery_row_to_ref(r) for r in rec_rows]
        )

        return get_nudge_queue(all_refs, max_items=max_items)

    # ── Tag history ───────────────────────────────────────────────────────────

    async def get_tag_history(
        self,
        user_id: str,
        limit: int = 20,
    ) -> list[dict]:
        """
        Return the most recent tagged windows (stress + recovery) for display.
        """
        uid = parse_uuid(user_id)
        if uid is None:
            return []

        s_res = await self._db.execute(
            select(StressWindow)
            .where(
                StressWindow.user_id == uid,
                StressWindow.tag != None,  # noqa: E711
            )
            .order_by(StressWindow.started_at.desc())
            .limit(limit)
        )
        r_res = await self._db.execute(
            select(RecoveryWindow)
            .where(
                RecoveryWindow.user_id == uid,
                RecoveryWindow.tag != None,  # noqa: E711
            )
            .order_by(RecoveryWindow.started_at.desc())
            .limit(limit)
        )
        stress_rows = list(s_res.scalars().all())
        rec_rows = list(r_res.scalars().all())

        items = [
            {
                "window_id": str(r.id),
                "window_type": "stress",
                "started_at": r.started_at.isoformat(),
                "tag": r.tag,
                "tag_source": r.tag_source,
                "suppression_pct": r.suppression_pct,
            }
            for r in stress_rows
        ] + [
            {
                "window_id": str(r.id),
                "window_type": "recovery",
                "started_at": r.started_at.isoformat(),
                "tag": r.tag,
                "tag_source": r.tag_source,
                "suppression_pct": None,
            }
            for r in rec_rows
        ]

        items.sort(key=lambda x: x["started_at"], reverse=True)
        return items[:limit]
