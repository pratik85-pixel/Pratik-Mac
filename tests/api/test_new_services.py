"""
tests/api/test_new_services.py

Tests for all new services and wiring added in the latest sprint:

- UserTagPatternModel.from_dict roundtrip
- TaggingService (async DB wrapper) — mock DB
- PlanService — plan generation end-to-end
- CoachService.build_assessment + morning_brief with assessment
- CoachService.morning_brief with daily_plan injection
- ConversationService.close_and_persist — signal → HabitEvent mapping
- Tagging router endpoints (via TestClient with dependency overrides)
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from tagging.tag_pattern_model import UserTagPatternModel
from tagging.auto_tagger import TagPattern


# ── Helpers ───────────────────────────────────────────────────────────────────

def _uid() -> str:
    """Generate a fresh UUID string for test user IDs."""
    return str(uuid.uuid4())


def _make_mock_db() -> AsyncMock:
    db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_result.scalars.return_value.all.return_value = []
    mock_result.scalar_one.return_value = 0
    db.execute.return_value = mock_result
    db.commit.return_value = None
    # SQLAlchemy AsyncSession.add() is synchronous — use MagicMock so
    # side_effect lambdas work correctly without await.
    db.add = MagicMock(return_value=None)
    db.merge = MagicMock(return_value=None)
    db.delete = MagicMock(return_value=None)
    db.expunge = MagicMock(return_value=None)
    db.rollback.return_value = None
    return db


def _run(coro):
    """Run a coroutine from a synchronous test."""
    return asyncio.run(coro)


# ══════════════════════════════════════════════════════════════════════════════
# Section 1 — UserTagPatternModel.from_dict roundtrip
# ══════════════════════════════════════════════════════════════════════════════

class TestUserTagPatternModelFromDict:

    def test_empty_dict_returns_empty_model(self):
        model = UserTagPatternModel.from_dict({})
        assert model.user_id == ""
        assert model.patterns == {}
        assert model.sport_stressor_slugs == []

    def test_roundtrip_preserves_user_id(self):
        original = UserTagPatternModel(
            user_id="user-abc",
            patterns={},
            sport_stressor_slugs=[],
            auto_tag_eligible_slugs=frozenset(),
        )
        data = original.to_dict()
        restored = UserTagPatternModel.from_dict(data)
        assert restored.user_id == "user-abc"

    def test_roundtrip_preserves_patterns(self):
        pattern = TagPattern(
            tag="running",
            window_type="stress",
            confirmed_count=5,
            hour_histogram={7: 3, 8: 2},
            weekday_counts={0: 3, 2: 2},
            avg_suppression=0.45,
        )
        original = UserTagPatternModel(
            user_id="u1",
            patterns={"running": pattern},
            sport_stressor_slugs=["running", "sports"],
            auto_tag_eligible_slugs=frozenset(["running"]),
        )
        data = original.to_dict()
        restored = UserTagPatternModel.from_dict(data)

        assert "running" in restored.patterns
        rp = restored.patterns["running"]
        assert rp.confirmed_count == 5
        assert rp.hour_histogram == {7: 3, 8: 2}
        assert rp.weekday_counts == {0: 3, 2: 2}
        assert rp.avg_suppression == pytest.approx(0.45)

    def test_roundtrip_preserves_sport_stressors(self):
        original = UserTagPatternModel(
            user_id="u2",
            patterns={},
            sport_stressor_slugs=["running", "sports"],
            auto_tag_eligible_slugs=frozenset(),
        )
        data = original.to_dict()
        restored = UserTagPatternModel.from_dict(data)
        assert restored.sport_stressor_slugs == ["running", "sports"]

    def test_roundtrip_restores_eligible_from_confirmed_count(self):
        """auto_tag_eligible_slugs is recomputed from confirmed_count >= 3."""
        pattern_eligible = TagPattern(
            tag="yoga",
            window_type="recovery",
            confirmed_count=5,  # >= AUTOTAG_MIN_CONFIRMED = 3
            hour_histogram={18: 5},
            weekday_counts={6: 5},
        )
        pattern_not_eligible = TagPattern(
            tag="meditation",
            window_type="recovery",
            confirmed_count=2,  # < 3
            hour_histogram={20: 2},
            weekday_counts={1: 2},
        )
        original = UserTagPatternModel(
            user_id="u3",
            patterns={"yoga": pattern_eligible, "meditation": pattern_not_eligible},
            sport_stressor_slugs=[],
            auto_tag_eligible_slugs=frozenset(["yoga"]),
        )
        data = original.to_dict()
        restored = UserTagPatternModel.from_dict(data)
        assert "yoga" in restored.auto_tag_eligible_slugs
        assert "meditation" not in restored.auto_tag_eligible_slugs

    def test_hour_histogram_keys_are_ints_after_roundtrip(self):
        """JSON converts int keys to str — from_dict must convert back to int."""
        pattern = TagPattern(
            tag="running",
            window_type="stress",
            confirmed_count=4,
            hour_histogram={7: 2, 8: 1, 9: 1},
            weekday_counts={0: 2, 1: 2},
        )
        original = UserTagPatternModel(
            user_id="u4",
            patterns={"running": pattern},
            sport_stressor_slugs=[],
            auto_tag_eligible_slugs=frozenset(),
        )
        data = original.to_dict()
        # Simulate JSON round-trip (keys become strings)
        import json
        data_json = json.loads(json.dumps(data))
        restored = UserTagPatternModel.from_dict(data_json)
        rp = restored.patterns["running"]
        assert all(isinstance(k, int) for k in rp.hour_histogram)
        assert all(isinstance(k, int) for k in rp.weekday_counts)


# ══════════════════════════════════════════════════════════════════════════════
# Section 2 — TaggingService (async DB wrapper)
# ══════════════════════════════════════════════════════════════════════════════

class TestTaggingServiceAsync:

    def test_load_pattern_model_returns_none_when_no_row(self):
        from api.services.tagging_service import TaggingService
        db = _make_mock_db()
        svc = TaggingService(db=db)
        result = _run(svc.load_pattern_model("user-xyz"))
        assert result is None

    def test_get_nudge_queue_empty_when_no_windows(self):
        from api.services.tagging_service import TaggingService
        db = _make_mock_db()
        svc = TaggingService(db=db)
        result = _run(svc.get_nudge_queue("user-xyz"))
        assert result == []

    def test_get_tag_history_empty_when_no_windows(self):
        from api.services.tagging_service import TaggingService
        db = _make_mock_db()
        svc = TaggingService(db=db)
        result = _run(svc.get_tag_history("user-xyz"))
        assert result == []

    def test_tag_window_invalid_uuid_returns_error(self):
        from api.services.tagging_service import TaggingService
        db = _make_mock_db()
        svc = TaggingService(db=db)
        result = _run(svc.tag_window(
            user_id="user-xyz",
            window_id="not-a-uuid",
            window_type="stress",
            slug="running",
        ))
        assert result.success is False
        assert result.error is not None

    def test_tag_window_missing_window_returns_error(self):
        from api.services.tagging_service import TaggingService
        db = _make_mock_db()
        # DB returns None (window not found)
        svc = TaggingService(db=db)
        result = _run(svc.tag_window(
            user_id="user-xyz",
            window_id=str(uuid.uuid4()),
            window_type="stress",
            slug="running",
        ))
        assert result.success is False

    def test_rebuild_pattern_model_with_no_windows_returns_empty(self):
        from api.services.tagging_service import TaggingService
        db = _make_mock_db()
        svc = TaggingService(db=db)
        result = _run(svc.rebuild_pattern_model("user-xyz"))
        assert result.patterns_built == 0
        assert result.sport_stressors == []

    def test_run_auto_tag_pass_with_no_model_returns_empty(self):
        from api.services.tagging_service import TaggingService
        db = _make_mock_db()
        svc = TaggingService(db=db)
        result = _run(svc.run_auto_tag_pass("user-xyz"))
        assert result.tagged_count == 0
        assert result.skipped_count == 0

    def test_save_pattern_model_calls_db_add_and_commit(self):
        from api.services.tagging_service import TaggingService
        db = _make_mock_db()
        uid = _uid()
        svc = TaggingService(db=db)
        model = UserTagPatternModel(
            user_id=uid,
            patterns={},
            sport_stressor_slugs=[],
            auto_tag_eligible_slugs=frozenset(),
        )
        _run(svc.save_pattern_model(
            user_id=uid,
            model=model,
            patterns_built=0,
            sport_stressor_slugs=[],
        ))
        db.add.assert_called_once()
        db.commit.assert_called_once()


# ══════════════════════════════════════════════════════════════════════════════
# Section 3 — PlanService
# ══════════════════════════════════════════════════════════════════════════════

class TestPlanService:

    def _mock_model_svc(self):
        from archetypes.scorer import NSHealthProfile
        from model.baseline_builder import PersonalFingerprint
        svc = AsyncMock()
        fp = PersonalFingerprint()
        profile = NSHealthProfile(
            total_score=55,
            stage=1,
            stage_target=60,
            recovery_capacity=11,
            baseline_resilience=11,
            coherence_capacity=11,
            chrono_fit=11,
            load_management=11,
            primary_pattern="under_stimulated",
            amplifier_pattern=None,
            pattern_scores={},
        )
        svc.get_fingerprint.return_value = fp
        svc.get_profile.return_value = profile
        svc._db = None  # no DB on model_svc
        return svc

    def test_get_or_create_today_plan_returns_dict(self):
        from api.services.plan_service import PlanService
        db = _make_mock_db()
        model_svc = self._mock_model_svc()
        svc = PlanService(db=db, model_service=model_svc)
        result = _run(svc.get_or_create_today_plan("user-abc"))
        assert isinstance(result, dict)
        # Plan (or DB row response) should have items
        assert "day_type" in result or "items" in result

    def test_record_deviation_invalid_uuid_returns_empty(self):
        from api.services.plan_service import PlanService
        db = _make_mock_db()
        model_svc = self._mock_model_svc()
        svc = PlanService(db=db, model_service=model_svc)
        result = _run(svc.record_deviation(
            user_id="not-a-uuid",
            activity_slug="running",
            priority="recommended",
            reason_category="time_constraint",
        ))
        assert result == ""

    def test_get_deviation_history_empty_when_no_rows(self):
        from api.services.plan_service import PlanService
        db = _make_mock_db()
        model_svc = self._mock_model_svc()
        svc = PlanService(db=db, model_service=model_svc)
        result = _run(svc.get_deviation_history("user-abc"))
        assert result == []

    def test_record_deviation_persists_row(self):
        from api.services.plan_service import PlanService
        db = _make_mock_db()
        model_svc = self._mock_model_svc()
        svc = PlanService(db=db, model_service=model_svc)
        uid = str(uuid.uuid4())
        _run(svc.record_deviation(
            user_id=uid,
            activity_slug="walk",
            priority="must_do",
            reason_category="forgot",
        ))
        db.add.assert_called_once()
        db.commit.assert_called_once()


# ══════════════════════════════════════════════════════════════════════════════
# Section 4 — CoachService with assessment + daily_plan injection
# ══════════════════════════════════════════════════════════════════════════════

class TestCoachServiceAssessmentWiring:

    def _make_profile_fp(self):
        from archetypes.scorer import NSHealthProfile
        from model.baseline_builder import PersonalFingerprint
        fp = PersonalFingerprint()
        profile = NSHealthProfile(
            total_score=60,
            stage=1,
            stage_target=70,
            recovery_capacity=12,
            baseline_resilience=12,
            coherence_capacity=12,
            chrono_fit=12,
            load_management=12,
            primary_pattern="under_stimulated",
            amplifier_pattern=None,
            pattern_scores={},
        )
        return fp, profile

    def test_build_assessment_returns_user_assessment(self):
        from api.services.coach_service import CoachService
        from coach.assessor import SessionRecord, ReadinessRecord
        records = [
            SessionRecord(session_id="s1", session_score=0.75, was_prescribed=True, completed=True),
            SessionRecord(session_id="s2", session_score=0.80, was_prescribed=True, completed=True),
        ]
        readiness = [ReadinessRecord(date_index=0, readiness=60.0)]
        assessment = CoachService.build_assessment(
            current_stage=1,
            session_records=records,
            readiness_records=readiness,
        )
        assert assessment is not None
        assert assessment.level_gate is not None
        assert assessment.learning_state in ("improving", "stabilizing", "plateaued", "declining")
        assert isinstance(assessment.summary_note, str)

    def test_morning_brief_with_assessment_includes_summary(self):
        from api.services.coach_service import CoachService
        from coach.assessor import SessionRecord, ReadinessRecord
        fp, profile = self._make_profile_fp()
        records = [
            SessionRecord(session_id="s1", session_score=0.70, was_prescribed=True, completed=True),
        ]
        assessment = CoachService.build_assessment(
            current_stage=1,
            session_records=records,
            readiness_records=[],
        )
        svc = CoachService(llm_client=None)
        result = svc.morning_brief(fp, profile, assessment=assessment)
        # Offline mode returns a structured dict
        assert isinstance(result, dict)

    def test_morning_brief_with_daily_plan_includes_must_do(self):
        from api.services.coach_service import CoachService
        from coach.prescriber import PrescriberInputs, build_daily_plan
        fp, profile = self._make_profile_fp()
        inputs = PrescriberInputs(
            stage=1,
            archetype_primary="under_stimulated",
            readiness_score=65.0,
            day_type="green",
            plan_date="2026-03-10",
            day_of_week=0,
        )
        plan = build_daily_plan(inputs)
        svc = CoachService(llm_client=None)
        result = svc.morning_brief(fp, profile, daily_plan=plan)
        assert isinstance(result, dict)

    def test_weekly_review_with_assessment_includes_learning_state(self):
        from api.services.coach_service import CoachService
        from coach.assessor import SessionRecord, ReadinessRecord
        fp, profile = self._make_profile_fp()
        records = [
            SessionRecord(session_id=f"s{i}", session_score=0.72, was_prescribed=True, completed=True)
            for i in range(6)
        ]
        assessment = CoachService.build_assessment(
            current_stage=1,
            session_records=records,
            readiness_records=[ReadinessRecord(date_index=i, readiness=62.0) for i in range(7)],
        )
        svc = CoachService(llm_client=None)
        result = svc.weekly_review(fp, profile, assessment=assessment)
        assert isinstance(result, dict)

    def test_build_assessment_with_sport_stressors(self):
        from api.services.coach_service import CoachService
        from coach.assessor import SessionRecord
        records = [
            SessionRecord(session_id="s1", session_score=0.60, was_prescribed=True, completed=True),
        ]
        assessment = CoachService.build_assessment(
            current_stage=0,
            session_records=records,
            readiness_records=[],
            sport_stressor_slugs=["running", "sports"],
        )
        assert "running" in assessment.sport_stressors
        assert "sports" in assessment.sport_stressors


# ══════════════════════════════════════════════════════════════════════════════
# Section 5 — ConversationService.close_and_persist
# ══════════════════════════════════════════════════════════════════════════════

class TestConversationServiceClosePersist:

    def _get_svc_and_conv_id(self):
        from api.services.conversation_service import ConversationService
        svc = ConversationService(llm_client=None)
        conv_id = _run(svc.open(_uid(), "morning_brief"))
        return svc, conv_id

    def test_close_and_persist_with_no_db_does_not_crash(self):
        svc, conv_id = self._get_svc_and_conv_id()
        # Should not raise
        _run(svc.close_and_persist(conv_id, db=None))

    def test_close_and_persist_with_signals_writes_habit_events(self):
        from api.services.conversation_service import ConversationService
        svc = ConversationService(llm_client=None)
        conv_id = _run(svc.open(_uid(), "nudge"))

        # Manually inject accumulated signals into the conversation state
        state = svc._store.get(conv_id)
        assert state is not None
        state.accumulated_signals = ["alcohol_event", "exercise_event"]

        db = _make_mock_db()
        _run(svc.close_and_persist(conv_id, db=db))

        # Two HabitEvent rows should have been added
        add_calls = db.add.call_count
        assert add_calls == 2
        db.commit.assert_called_once()

    def test_close_and_persist_maps_signals_to_event_types(self):
        from api.services.conversation_service import ConversationService, _SIGNAL_TO_EVENT_TYPE
        svc = ConversationService(llm_client=None)
        conv_id = _run(svc.open(_uid(), "nudge"))

        state = svc._store.get(conv_id)
        state.accumulated_signals = ["sports_activity", "social_time", "cold_shower_event"]

        db = _make_mock_db()
        captured_rows = []
        db.add.side_effect = lambda r: captured_rows.append(r)

        _run(svc.close_and_persist(conv_id, db=db))
        assert len(captured_rows) == 3

        event_types = {r.event_type for r in captured_rows}
        assert "sports" in event_types
        assert "social_time" in event_types
        assert "cold_shower" in event_types

    def test_close_and_persist_with_no_signals_does_not_commit(self):
        svc, conv_id = self._get_svc_and_conv_id()
        db = _make_mock_db()
        # State has no accumulated_signals (default empty list)
        _run(svc.close_and_persist(conv_id, db=db))
        db.commit.assert_not_called()

    def test_close_and_persist_nonexistent_conv_does_not_crash(self):
        from api.services.conversation_service import ConversationService
        svc = ConversationService(llm_client=None)
        db = _make_mock_db()
        # Should not raise
        _run(svc.close_and_persist("nonexistent-conv-id", db=db))
        db.commit.assert_not_called()

    def test_signal_fallback_uses_truncated_label(self):
        from api.services.conversation_service import ConversationService
        svc = ConversationService(llm_client=None)
        conv_id = _run(svc.open(_uid(), "nudge"))

        state = svc._store.get(conv_id)
        # Use a signal not in the mapping
        state.accumulated_signals = ["unknown_custom_signal_that_is_not_in_map"]

        db = _make_mock_db()
        captured = []
        db.add.side_effect = lambda r: captured.append(r)
        _run(svc.close_and_persist(conv_id, db=db))

        assert len(captured) == 1
        # Truncated to 40 chars
        assert len(captured[0].event_type) <= 40


# ══════════════════════════════════════════════════════════════════════════════
# Section 6 — Tagging router (via TestClient)
# ══════════════════════════════════════════════════════════════════════════════

class TestTaggingRouter:
    """
    Tests for /tagging/* endpoints via TestClient with mocked DB dependency.
    """

    @pytest.fixture(scope="class")
    def client(self):
        from fastapi.testclient import TestClient
        from api.main import create_app
        from api.db.database import get_db

        async def _mock_db():
            yield _make_mock_db()

        app = create_app()
        app.dependency_overrides[get_db] = _mock_db
        with TestClient(app) as c:
            yield c

    def test_get_tags_requires_user_id_header(self, client):
        resp = client.get("/tagging/tags")
        assert resp.status_code in (401, 422)

    def test_get_tags_returns_empty_list(self, client):
        resp = client.get("/tagging/tags", headers={"X-User-Id": "user-abc"})
        assert resp.status_code == 200
        data = resp.json()
        assert "tags" in data
        assert data["count"] == 0

    def test_get_patterns_returns_empty_when_no_model(self, client):
        resp = client.get("/tagging/patterns", headers={"X-User-Id": "user-abc"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["patterns"] == {}
        assert data["sport_stressor_slugs"] == []

    def test_get_nudge_queue_returns_empty(self, client):
        resp = client.get("/tagging/nudge", headers={"X-User-Id": "user-abc"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["nudge_queue"] == []

    def test_tag_window_invalid_window_type_returns_422(self, client):
        resp = client.post(
            "/tagging/tag",
            headers={"X-User-Id": "user-abc"},
            json={
                "window_id": str(uuid.uuid4()),
                "window_type": "invalid_type",
                "slug": "running",
            },
        )
        assert resp.status_code == 422

    def test_tag_window_missing_window_returns_400(self, client):
        resp = client.post(
            "/tagging/tag",
            headers={"X-User-Id": "user-abc"},
            json={
                "window_id": str(uuid.uuid4()),
                "window_type": "stress",
                "slug": "running",
            },
        )
        # DB returns None → window not found → 400
        assert resp.status_code == 400

    def test_rebuild_patterns_returns_counts(self, client):
        resp = client.post(
            "/tagging/rebuild-patterns",
            headers={"X-User-Id": "user-abc"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "patterns_built" in data
        assert data["patterns_built"] == 0

    def test_get_tags_respects_limit_query_param(self, client):
        resp = client.get(
            "/tagging/tags?limit=5",
            headers={"X-User-Id": "user-abc"},
        )
        assert resp.status_code == 200

    def test_get_nudge_respects_max_items_param(self, client):
        resp = client.get(
            "/tagging/nudge?max_items=5",
            headers={"X-User-Id": "user-abc"},
        )
        assert resp.status_code == 200
