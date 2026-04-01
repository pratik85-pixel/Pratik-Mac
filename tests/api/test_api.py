"""
tests/api/test_api.py

API layer tests — runs without a real database using dependency overrides.

Pattern
-------
- `get_db` is overridden with `mock_db()` — an AsyncMock that returns
  configurable results from `execute()`.
- Singleton services (session, coach, conversation) are initialised normally
  via the app's lifespan; they run in offline mode (no LLM, no DB).
- Service-level tests (SessionService, CoachService, ModelService) do not
  use the HTTP layer at all.
"""

from __future__ import annotations

import asyncio
import time
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.db.database import get_db
from api.services.session_service import SessionService, LiveMetrics
from api.services.model_service import ModelService
from api.services.coach_service import CoachService
from api.config import get_settings


# ── Fixtures ───────────────────────────────────────────────────────────────────

def _make_mock_db() -> AsyncMock:
    """
    Create an AsyncMock that acts like an AsyncSession.
    `execute()` returns an object where `.scalar_one_or_none()` is None.
    `.scalars().first()` must be None — otherwise ORM rows become MagicMocks and
    break numeric comparisons in TrackingService (e.g. morning recap).
    """
    db = AsyncMock()
    scalar_result = MagicMock()
    scalar_result.scalar_one_or_none.return_value = None
    # COUNT(...) queries use .scalar(); default 0 so nudge cap logic compares ints.
    scalar_result.scalar.return_value = 0
    scalars_result = MagicMock()
    scalars_result.all.return_value = []
    scalars_result.first.return_value = None
    scalar_result.scalars.return_value = scalars_result
    db.execute.return_value = scalar_result
    db.commit.return_value = None
    db.add.return_value = None
    db.merge.return_value = None
    db.rollback.return_value = None
    db.close.return_value = None
    return db


async def _mock_db_dependency() -> AsyncGenerator:
    yield _make_mock_db()


@pytest.fixture(scope="module")
def app():
    """Create and configure the test application (once per module)."""
    _app = create_app()
    _app.dependency_overrides[get_db] = _mock_db_dependency
    return _app


@pytest.fixture(scope="module")
def client(app):
    """
    Synchronous TestClient — triggers lifespan on enter, tears down on exit.
    All route tests share this client.
    """
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


# ── Config tests ───────────────────────────────────────────────────────────────

class TestConfig:

    def test_default_llm_disabled(self):
        cfg = get_settings()
        assert cfg.LLM_ENABLED is False

    def test_default_window_seconds(self):
        cfg = get_settings()
        assert cfg.WINDOW_SECONDS == 60

    def test_min_beats_positive(self):
        cfg = get_settings()
        assert cfg.MIN_BEATS_PER_WINDOW > 0


# ── Health endpoint ────────────────────────────────────────────────────────────

class TestHealth:

    def test_health_returns_200(self, client):
        r = client.get("/health")
        assert r.status_code == 200

    def test_health_has_status_ok(self, client):
        r = client.get("/health")
        assert r.json()["status"] == "ok"

    def test_health_has_version(self, client):
        r = client.get("/health")
        assert "version" in r.json()

    def test_health_shows_active_sessions(self, client):
        r = client.get("/health")
        assert "active_sessions" in r.json()


# ── Session endpoints ──────────────────────────────────────────────────────────

class TestSessionEndpoints:

    _HEADERS = {"x-user-id": "test-user-001"}

    def test_start_session_returns_session_id(self, client):
        r = client.post(
            "/session/start",
            json={"prf_status": "unknown"},
            headers=self._HEADERS,
        )
        assert r.status_code == 200
        data = r.json()
        assert "session_id" in data
        assert isinstance(data["session_id"], str) and len(data["session_id"]) > 0

    def test_start_session_returns_practice_type(self, client):
        r = client.post(
            "/session/start",
            json={"prf_status": "unknown"},
            headers=self._HEADERS,
        )
        assert "practice_type" in r.json()

    def test_start_session_returns_duration(self, client):
        r = client.post(
            "/session/start",
            json={},
            headers=self._HEADERS,
        )
        data = r.json()
        assert "duration_minutes" in data
        assert data["duration_minutes"] > 0

    def test_end_session_unknown_id_returns_404(self, client):
        r = client.post(
            "/session/nonexistent-id/end",
            json={},
            headers=self._HEADERS,
        )
        assert r.status_code == 404

    def test_live_metrics_unknown_session_returns_404(self, client):
        r = client.get(
            "/session/nonexistent/live",
            headers=self._HEADERS,
        )
        assert r.status_code == 404

    def test_missing_user_id_header_returns_422(self, client):
        r = client.post("/session/start", json={})
        assert r.status_code == 422

    def test_full_session_lifecycle(self, client):
        """Start → end (no PPI data → 404 on end since no windows recorded)."""
        start = client.post(
            "/session/start",
            json={"prf_status": "unknown"},
            headers=self._HEADERS,
        )
        assert start.status_code == 200
        session_id = start.json()["session_id"]

        # Ending with no PPI data returns 404
        end = client.post(
            f"/session/{session_id}/end",
            json={},
            headers=self._HEADERS,
        )
        assert end.status_code == 404, f"Expected 404 for empty session, got {end.status_code}"


# ── User endpoints ─────────────────────────────────────────────────────────────

class TestUserEndpoints:

    _HEADERS = {"x-user-id": "test-user-001"}

    def test_get_profile_user_not_found_returns_404(self, client):
        # DB mock returns None → user not found
        r = client.get("/user/profile", headers=self._HEADERS)
        assert r.status_code == 404

    def test_get_fingerprint_returns_200(self, client):
        """ModelService(db=None) always returns an empty fingerprint."""
        r = client.get("/user/fingerprint", headers=self._HEADERS)
        assert r.status_code == 200

    def test_get_archetype_returns_200(self, client):
        r = client.get("/user/archetype", headers=self._HEADERS)
        assert r.status_code == 200

    def test_get_archetype_has_stage(self, client):
        r = client.get("/user/archetype", headers=self._HEADERS)
        assert "stage" in r.json()

    def test_get_archetype_has_dimension_scores(self, client):
        r = client.get("/user/archetype", headers=self._HEADERS)
        assert "dimension_scores" in r.json()

    def test_get_habits_returns_200(self, client):
        r = client.get("/user/habits", headers=self._HEADERS)
        assert r.status_code == 200

    def test_update_habits_returns_200(self, client):
        r = client.put(
            "/user/habits",
            json={"alcohol": "never", "caffeine": "none"},
            headers=self._HEADERS,
        )
        assert r.status_code == 200

    def test_update_habits_returns_updated_fields(self, client):
        r = client.put(
            "/user/habits",
            json={"sleep_schedule": "irregular"},
            headers=self._HEADERS,
        )
        data = r.json()
        assert "sleep_schedule" in data["updated_fields"]


# ── Plan endpoints ─────────────────────────────────────────────────────────────

class TestPlanEndpoints:

    _HEADERS = {"x-user-id": "test-user-001"}

    def test_plan_today_returns_200(self, client):
        r = client.get("/plan/today", headers=self._HEADERS)
        assert r.status_code == 200

    def test_plan_today_has_scoring_contract_fields(self, client):
        r = client.get("/plan/today", headers=self._HEADERS)
        j = r.json()
        assert j.get("metrics_contract_id") == "zenflow_locked_v1"
        assert j.get("readiness_formula_id") == "composite_readiness_v2"

    def test_plan_today_shape_when_present(self, client):
        r = client.get("/plan/today", headers=self._HEADERS)
        j = r.json()
        if j.get("id") is not None:
            assert "items" in j
            assert "readiness_score" in j

    def test_plan_week_returns_200(self, client):
        r = client.get("/plan/week", headers=self._HEADERS)
        assert r.status_code == 200

    def test_check_in_valid_returns_200(self, client):
        r = client.post(
            "/plan/check-in",
            json={"reactivity": 3, "focus": 4, "recovery": 4},
            headers=self._HEADERS,
        )
        assert r.status_code == 200

    def test_check_in_returns_composite_score(self, client):
        r = client.post(
            "/plan/check-in",
            json={"reactivity": 5, "focus": 5, "recovery": 5},
            headers=self._HEADERS,
        )
        assert r.json()["composite_score"] == 100

    def test_check_in_out_of_range_returns_422(self, client):
        r = client.post(
            "/plan/check-in",
            json={"reactivity": 6, "focus": 3, "recovery": 3},
            headers=self._HEADERS,
        )
        assert r.status_code == 422

    def test_check_in_zero_returns_422(self, client):
        r = client.post(
            "/plan/check-in",
            json={"reactivity": 0, "focus": 3, "recovery": 3},
            headers=self._HEADERS,
        )
        assert r.status_code == 422


# ── Coach endpoints ────────────────────────────────────────────────────────────

class TestCoachEndpoints:

    _HEADERS = {"x-user-id": "test-user-001"}

    def test_morning_brief_returns_200(self, client):
        r = client.get("/coach/morning-brief", headers=self._HEADERS)
        assert r.status_code == 200

    def test_morning_brief_has_summary(self, client):
        r = client.get("/coach/morning-brief", headers=self._HEADERS)
        data = r.json()
        # local_engine always produces a summary key
        assert "summary" in data or any(k in data for k in ("reply", "action", "message"))

    def test_nudge_returns_200(self, client):
        r = client.get("/coach/nudge", headers=self._HEADERS)
        assert r.status_code == 200

    def test_post_session_unknown_session_returns_404(self, client):
        r = client.get(
            "/coach/post-session?session_id=nonexistent",
            headers=self._HEADERS,
        )
        assert r.status_code == 404

    def test_conversation_history_returns_200(self, client):
        r = client.get("/coach/conversation/history", headers=self._HEADERS)
        assert r.status_code == 200
        assert "turns" in r.json()

    def test_conversation_turn_starts_session(self, client):
        r = client.post(
            "/coach/conversation",
            json={"message": "I feel really stressed today"},
            headers=self._HEADERS,
        )
        assert r.status_code == 200
        data = r.json()
        assert "conversation_id" in data
        assert isinstance(data["conversation_id"], str)

    def test_conversation_turn_sets_session_open(self, client):
        r = client.post(
            "/coach/conversation",
            json={"message": "Good morning"},
            headers=self._HEADERS,
        )
        assert r.status_code == 200
        data = r.json()
        assert "session_open" in data


# ── Outcomes endpoints ─────────────────────────────────────────────────────────

class TestOutcomeEndpoints:

    _HEADERS = {"x-user-id": "test-user-001"}

    def test_report_card_returns_200(self, client):
        """Returns empty report card when DB returns no rows."""
        r = client.get("/outcomes/report-card", headers=self._HEADERS)
        assert r.status_code == 200

    def test_report_card_has_sessions_done(self, client):
        r = client.get("/outcomes/report-card", headers=self._HEADERS)
        assert "sessions_done" in r.json()

    def test_weekly_returns_200(self, client):
        r = client.get("/outcomes/weekly", headers=self._HEADERS)
        assert r.status_code == 200

    def test_recompute_returns_200(self, client):
        r = client.post("/outcomes/recompute", headers=self._HEADERS)
        assert r.status_code == 200


# ── SessionService unit tests ──────────────────────────────────────────────────

class TestSessionServiceUnit:
    """
    Tests for the in-memory session processing pipeline.
    Does not use HTTP.
    """

    def _svc(self) -> SessionService:
        return SessionService()

    def _make_practice(self):
        from sessions.session_prescriber import prescribe_session, PRF_UNKNOWN
        return prescribe_session(stage=0, prf_status=PRF_UNKNOWN, total_sessions_completed=0)

    def test_start_returns_uuid(self):
        svc = self._svc()
        sid = svc.start_session("user-1", self._make_practice())
        assert len(sid) == 36  # UUID format

    def test_active_count_increments(self):
        svc = self._svc()
        p   = self._make_practice()
        svc.start_session("u1", p)
        svc.start_session("u2", p)
        assert svc.active_count() == 2

    def test_is_active_true_after_start(self):
        svc = self._svc()
        sid = svc.start_session("u1", self._make_practice())
        assert svc.is_active(sid) is True

    def test_is_active_false_after_end(self):
        svc = self._svc()
        sid = svc.start_session("u1", self._make_practice())
        svc.end_session(sid)
        assert svc.is_active(sid) is False

    def test_end_unknown_session_returns_none(self):
        svc = self._svc()
        assert svc.end_session("no-such-id") is None

    def test_ingest_ppi_unknown_session_returns_none(self):
        svc = self._svc()
        assert svc.ingest_ppi("no-such-id", [800, 810], [0.0, 0.8]) is None

    def test_ingest_ppi_returns_live_metrics(self):
        svc = self._svc()
        sid = svc.start_session("u1", self._make_practice())
        ppi = [800.0 + i for i in range(50)]
        ts  = [i * 0.8 for i in range(50)]
        metrics = svc.ingest_ppi(sid, ppi, ts)
        assert metrics is not None
        assert isinstance(metrics, LiveMetrics)
        assert metrics.session_id == sid
        assert metrics.elapsed_s >= 0.0

    def test_get_live_metrics_after_ingest(self):
        svc = self._svc()
        sid = svc.start_session("u1", self._make_practice())
        ppi = [820.0] * 30
        ts  = [i * 1.0 for i in range(30)]
        svc.ingest_ppi(sid, ppi, ts)
        m = svc.get_live_metrics(sid)
        assert m is not None

    def test_get_live_metrics_unknown_session_returns_none(self):
        svc = self._svc()
        assert svc.get_live_metrics("no-such-id") is None

    def test_get_cached_outcome_initially_none(self):
        svc = self._svc()
        assert svc.get_cached_outcome("any-id") is None

    def test_end_session_caches_outcome_when_data_present(self):
        """A session with enough PPI data should cache an outcome on end."""
        svc = self._svc()
        sid = svc.start_session("u1", self._make_practice())

        # Feed 90 seconds of synthetic PPI (sufficient for a coherence window)
        ppi = [800.0 + 30 * np.sin(2 * np.pi * (6 / 60) * t)
               for t in np.linspace(0, 90, 110)]
        ts  = list(np.linspace(0, 90, 110))
        svc.ingest_ppi(sid, ppi, ts)
        outcome = svc.end_session(sid)

        assert outcome is not None
        assert svc.get_cached_outcome(sid) is outcome


# ── ModelService unit tests ────────────────────────────────────────────────────

class TestModelServiceUnit:

    def test_get_fingerprint_offline_returns_empty(self):
        svc = ModelService(db=None)
        fp = asyncio.run(svc.get_fingerprint("any-user"))
        assert fp is not None
        # Empty fingerprint has no floor yet
        assert fp.rmssd_floor is None

    def test_get_profile_offline_returns_stage_0(self):
        svc = ModelService(db=None)
        profile = asyncio.run(svc.get_profile("any-user"))
        assert profile is not None
        assert isinstance(profile.stage, int)
        assert 0 <= profile.stage <= 4

    def test_get_user_offline_returns_none(self):
        svc = ModelService(db=None)
        user = asyncio.run(svc.get_user("any-user"))
        assert user is None


# ── CoachService unit tests ────────────────────────────────────────────────────

class TestCoachServiceUnit:

    def _svc(self) -> CoachService:
        return CoachService(llm_client=None)  # offline

    def _fp_and_profile(self):
        from model.baseline_builder import PersonalFingerprint
        from archetypes.scorer import compute_ns_health_profile
        fp      = PersonalFingerprint()
        profile = compute_ns_health_profile(fp)
        return fp, profile

    def test_morning_brief_returns_dict(self):
        svc          = self._svc()
        fp, profile  = self._fp_and_profile()
        result       = svc.morning_brief(fp, profile)
        assert isinstance(result, dict)

    def test_morning_brief_has_summary(self):
        svc         = self._svc()
        fp, profile = self._fp_and_profile()
        result      = svc.morning_brief(fp, profile)
        assert "summary" in result or "reply" in result

    def test_nudge_returns_dict(self):
        svc         = self._svc()
        fp, profile = self._fp_and_profile()
        result      = svc.nudge(fp, profile)
        assert isinstance(result, dict)

    def test_weekly_review_returns_dict(self):
        svc         = self._svc()
        fp, profile = self._fp_and_profile()
        result      = svc.weekly_review(fp, profile)
        assert isinstance(result, dict)
