import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from api.db.schema import Session as SessionRow
from api.utils import parse_uuid
from outcomes.session_outcomes import SessionOutcome
from outcomes.weekly_outcomes import compute_weekly_summary
from outcomes.longitudinal_outcomes import calculate_longitudinal_arc
from outcomes.report_builder import generate_outcome_report

UTC = timezone.utc


class OutcomeService:

    def __init__(
        self,
        db: Optional[AsyncSession] = None,
        model_service=None,
    ) -> None:
        self._db = db
        self._model_service = model_service

    # ── Session persistence ────────────────────────────────────────────────────

    async def persist_session_outcome(
        self,
        user_id: str,
        outcome: SessionOutcome,
    ) -> str:
        """
        Write a completed SessionOutcome to the `sessions` table.

        Returns the new row's UUID string (which becomes the canonical session_id
        returned to the client).
        """
        uid = parse_uuid(user_id)
        if uid is None:
            raise ValueError(f"Invalid user_id: {user_id!r}")

        now = datetime.now(UTC)
        started_at = now - timedelta(minutes=max(outcome.duration_minutes, 1))

        # session_score in DB is stored on 0–100 scale; outcome has 0.0–1.0
        score_100 = (
            round(outcome.session_score * 100, 1)
            if outcome.session_score is not None
            else None
        )

        row = SessionRow(
            id=uuid.uuid4(),
            user_id=uid,
            started_at=started_at,
            ended_at=now,
            context="session",
            practice_type=outcome.practice_type,
            session_score=score_100,
            coherence_avg=outcome.coherence_avg,
            rmssd_pre=outcome.pre_rmssd_ms,
            rmssd_post=outcome.post_rmssd_ms,
            # zone_1-4_seconds not captured in SessionOutcome dataclass yet
            zone_1_seconds=None,
            zone_2_seconds=None,
            zone_3_seconds=None,
            zone_4_seconds=None,
            config_version=1,
        )

        self._db.add(row)
        await self._db.commit()
        await self._db.refresh(row)
        return str(row.id)

    # ── Longitudinal / reporting helpers ──────────────────────────────────────

    def get_weekly_summary(self, data: List[Dict[str, Any]]):
        return compute_weekly_summary(data)

    def get_longitudinal_arc(self, recent_30: List[Dict[str, Any]], previous_30: List[Dict[str, Any]]):
        return calculate_longitudinal_arc(recent_30, previous_30)

    def get_outcome_report(self, weekly_data: List[Dict[str, Any]], recent_30: List[Dict[str, Any]], previous_30: List[Dict[str, Any]]):
        return generate_outcome_report(weekly_data, recent_30, previous_30)
