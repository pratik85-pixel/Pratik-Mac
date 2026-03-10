"""
api/services/outcome_service.py

Runs outcome computations and persists results to the database.

Responsibilities
----------------
- Persist a completed `SessionOutcome` to the `sessions` table.
- Compute and persist a `WeeklyOutcome` on demand or on schedule.
- Return structured report-card payload for the UI.
- Coordinate fingerprint updates via `ModelService`.

Design
------
Stateless service — accepts `AsyncSession` and `ModelService` at call time
so it can be used both as a FastAPI dependency and in background tasks.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, date, timedelta, UTC
from typing import Optional

from sqlalchemy import select, func as sqlfunc
from sqlalchemy.ext.asyncio import AsyncSession

from outcomes.session_outcomes import SessionOutcome
from coach.assessor import (
    assess_user,
    SessionRecord as AssessorSessionRecord,
    ReadinessRecord,
)
from api.db.schema import Session as SessionRow, WeeklyOutcome
from api.services.model_service import ModelService
from api.utils import parse_uuid

logger = logging.getLogger(__name__)


class OutcomeService:

    def __init__(
        self,
        model_service: ModelService,
        db: Optional[AsyncSession] = None,
    ) -> None:
        self._model_svc = model_service
        self._db        = db

    # ── Session outcome ────────────────────────────────────────────────────────

    async def persist_session_outcome(
        self,
        user_id: str,
        outcome: SessionOutcome,
    ) -> str:
        """Save the SessionOutcome to the `sessions` table and return the row id."""
        row = SessionRow(
            id              = uuid.UUID(outcome.session_id) if outcome.session_id else uuid.uuid4(),
            user_id         = parse_uuid(user_id) or uuid.uuid4(),
            started_at      = datetime.now(UTC),
            ended_at        = datetime.now(UTC),
            context         = "session",
            practice_type   = outcome.practice_type,
            session_score   = outcome.session_score,
            coherence_avg   = outcome.coherence_avg,
            zone_1_seconds  = outcome.zone_1_seconds,
            zone_2_seconds  = outcome.zone_2_seconds,
            zone_3_seconds  = outcome.zone_3_seconds,
            zone_4_seconds  = outcome.zone_4_seconds,
            rmssd_pre       = outcome.rmssd_pre_ms,
            rmssd_post      = outcome.rmssd_post_ms,
            config_version  = 1,
        )

        if self._db is not None:
            self._db.add(row)
            await self._db.commit()

        # Trigger fingerprint update
        await self._model_svc.update_fingerprint_from_outcome(user_id, outcome)

        logger.info(
            "outcome_persisted user=%s session=%s score=%.2f",
            user_id, row.id, outcome.session_score,
        )
        return str(row.id)

    # ── Weekly outcomes ────────────────────────────────────────────────────────

    async def compute_weekly_report(self, user_id: str) -> dict:
        """
        Compute a weekly report card for `user_id`.
        Returns a dict ready for the /outcomes/report-card endpoint.
        """
        if self._db is None:
            return _empty_report_card(user_id)

        uid        = parse_uuid(user_id)
        if uid is None:
            return _empty_report_card(user_id)
        week_start = _this_week_start()

        result = await self._db.execute(
            select(SessionRow)
            .where(SessionRow.user_id == uid)
            .where(SessionRow.started_at >= week_start)
            .order_by(SessionRow.started_at)
        )
        sessions: list[SessionRow] = list(result.scalars().all())

        n_sessions       = len(sessions)
        scores           = [s.session_score for s in sessions if s.session_score is not None]
        coherence_avgs   = [s.coherence_avg  for s in sessions if s.coherence_avg  is not None]
        z3_seconds       = sum(s.zone_3_seconds or 0.0 for s in sessions)
        z4_seconds       = sum(s.zone_4_seconds or 0.0 for s in sessions)

        resilience_avg = float(sum(scores) / len(scores)) * 100 if scores else None
        coherence_avg  = float(sum(coherence_avgs) / len(coherence_avgs)) if coherence_avgs else None

        profile   = await self._model_svc.get_profile(user_id)
        stage     = profile.stage

        # ── Run 3-gate assessor ──────────────────────────────────────────────
        assessor_records = [
            AssessorSessionRecord(
                session_id=str(s.id),
                session_score=(s.session_score / 100.0) if s.session_score is not None else None,
                was_prescribed=False,  # conservative — no plan records cross-referenced here
                completed=True,
            )
            for s in sessions
        ]
        assessment = assess_user(
            current_stage=stage,
            session_records=assessor_records,
            readiness_records=[],  # morning reads not loaded here — assessor will use defaults
        )

        report = {
            "user_id":          user_id,
            "week_start":       week_start.isoformat(),
            "sessions_done":    n_sessions,
            "sessions_planned": _sessions_planned(stage),
            "resilience_avg":   resilience_avg,
            "coherence_avg":    round(coherence_avg, 3) if coherence_avg else None,
            "zone3_4_minutes":  round((z3_seconds + z4_seconds) / 60, 1),
            "stage":            stage,
            # Level advancement (new 3-gate system)
            "level_gate": {
                "ready":         assessment.level_gate.ready,
                "next_stage":    assessment.level_gate.next_stage,
                "blocking":      assessment.level_gate.blocking,
                "floor_met":     assessment.level_gate.floor_met,
            },
            "learning_state":   assessment.learning_state,
            "summary_note":     assessment.summary_note,
        }

        # Persist weekly row
        row = WeeklyOutcome(
            user_id           = uid,
            week_start        = week_start,
            computed_at       = datetime.now(UTC),
            config_version    = 1,
            resilience_avg    = resilience_avg,
            sessions_completed= n_sessions,
            sessions_planned  = _sessions_planned(stage),
            zone3_total_minutes = (z3_seconds + z4_seconds) / 60,
            report_json       = report,
        )
        await self._db.merge(row)
        await self._db.commit()

        return report

    async def get_report_card(self, user_id: str) -> dict:
        """Return the most recently computed weekly report (cached row or fresh)."""
        if self._db is None:
            return _empty_report_card(user_id)

        uid    = parse_uuid(user_id)
        if uid is None:
            return _empty_report_card(user_id)
        result = await self._db.execute(
            select(WeeklyOutcome)
            .where(WeeklyOutcome.user_id == uid)
            .order_by(WeeklyOutcome.computed_at.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if row and row.report_json:
            return row.report_json

        return await self.compute_weekly_report(user_id)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _this_week_start() -> datetime:
    today = date.today()
    start = today - timedelta(days=today.weekday())  # Monday
    return datetime(start.year, start.month, start.day, tzinfo=UTC)


def _sessions_planned(stage: int) -> int:
    """Weekly session target by training stage."""
    _MAP = {0: 3, 1: 4, 2: 5, 3: 5, 4: 6, 5: 6}
    return _MAP.get(stage, 4)


def _empty_report_card(user_id: str) -> dict:
    return {
        "user_id":          user_id,
        "week_start":       _this_week_start().isoformat(),
        "sessions_done":    0,
        "sessions_planned": 4,
        "resilience_avg":   None,
        "coherence_avg":    None,
        "zone3_4_minutes":  0.0,
        "stage":            0,
        "level_gate": {
            "ready":      False,
            "next_stage": 1,
            "blocking":   ["insufficient_sessions"],
            "floor_met":  False,
        },
        "learning_state": "stabilizing",
        "summary_note":   "No session history yet.",
    }
