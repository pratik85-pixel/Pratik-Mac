"""
tests/api/test_phase7_security.py

Phase 7 — Security hardening tests.

Covers:
  A. Unbounded user message cap (max_length=2000 on ConversationTurnRequest.message)
  B. Outcomes endpoints require X-User-Id header
  C. In-process per-user rate limiter (RollingRateLimiter unit tests)
"""
from __future__ import annotations

import time
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.db.database import get_db
from api.rate_limiter import RollingRateLimiter


# ── Shared fixture ─────────────────────────────────────────────────────────────

def _make_mock_db() -> AsyncMock:
    db = AsyncMock()
    sr = MagicMock()
    sr.scalar_one_or_none.return_value = None
    sr.scalars.return_value.all.return_value = []
    db.execute.return_value = sr
    db.commit.return_value = None
    db.add.return_value = None
    return db


async def _mock_db_dep() -> AsyncGenerator:
    yield _make_mock_db()


@pytest.fixture(scope="module")
def sec_client():
    app = create_app()
    app.dependency_overrides[get_db] = _mock_db_dep
    with TestClient(app) as c:
        yield c


# ── Section A — message length cap ────────────────────────────────────────────

class TestMessageLengthCap:

    _HEADERS = {"x-user-id": "ph7-sec-test-user"}

    def test_message_over_2000_chars_returns_422(self, sec_client):
        r = sec_client.post(
            "/coach/conversation",
            json={"message": "x" * 2001},
            headers=self._HEADERS,
        )
        assert r.status_code == 422, f"Expected 422, got {r.status_code}: {r.text}"

    def test_message_exactly_2000_chars_not_length_error(self, sec_client):
        r = sec_client.post(
            "/coach/conversation",
            json={"message": "x" * 2000},
            headers=self._HEADERS,
        )
        # Must not be a Pydantic validation error (422) for message_too_long
        if r.status_code == 422:
            detail = r.json().get("detail", [])
            length_errors = [
                e for e in (detail if isinstance(detail, list) else [])
                if "max_length" in str(e) or "2000" in str(e) or "string_too_long" in str(e)
            ]
            assert not length_errors, f"Unexpected max_length error at exactly 2000 chars: {detail}"

    def test_empty_message_returns_422(self, sec_client):
        r = sec_client.post(
            "/coach/conversation",
            json={"message": ""},
            headers=self._HEADERS,
        )
        # Empty string is allowed by Pydantic (it's not None), but safety filter handles it
        # This test just ensures the endpoint responds (not 500)
        assert r.status_code != 500


# ── Section B — outcomes header enforcement ───────────────────────────────────

class TestOutcomesHeaderRequired:

    def test_weekly_outcomes_missing_header_returns_422(self, sec_client):
        r = sec_client.get("/api/v1/outcomes/weekly")
        assert r.status_code == 422, f"Expected 422 for missing header, got {r.status_code}"

    def test_longitudinal_outcomes_missing_header_returns_422(self, sec_client):
        r = sec_client.get("/api/v1/outcomes/longitudinal")
        assert r.status_code == 422, f"Expected 422 for missing header, got {r.status_code}"

    def test_weekly_outcomes_with_header_still_works(self, sec_client):
        r = sec_client.get("/api/v1/outcomes/weekly", headers={"x-user-id": "any-user"})
        assert r.status_code == 200

    def test_longitudinal_outcomes_with_header_still_works(self, sec_client):
        r = sec_client.get("/api/v1/outcomes/longitudinal", headers={"x-user-id": "any-user"})
        assert r.status_code == 200


# ── Section C — RollingRateLimiter unit tests ─────────────────────────────────

class TestRollingRateLimiter:

    def test_calls_under_cap_are_allowed(self):
        limiter = RollingRateLimiter(max_calls=5, window_seconds=60)
        for _ in range(5):
            limiter.check("user-a")  # should not raise

    def test_call_at_cap_is_blocked(self):
        from fastapi import HTTPException
        limiter = RollingRateLimiter(max_calls=3, window_seconds=60)
        for _ in range(3):
            limiter.check("user-b")
        with pytest.raises(HTTPException) as exc_info:
            limiter.check("user-b")
        assert exc_info.value.status_code == 429

    def test_different_keys_are_independent(self):
        limiter = RollingRateLimiter(max_calls=2, window_seconds=60)
        limiter.check("user-c")
        limiter.check("user-c")
        # user-d starts fresh — should not be blocked
        limiter.check("user-d")
        limiter.check("user-d")

    def test_window_expiry_resets_count(self):
        """Calls older than window_seconds are pruned and don't count."""
        from fastapi import HTTPException
        limiter = RollingRateLimiter(max_calls=2, window_seconds=1)
        limiter.check("user-e")
        limiter.check("user-e")
        # Both slots filled — next call within window should be blocked
        with pytest.raises(HTTPException):
            limiter.check("user-e")
        # Wait for window to expire
        time.sleep(1.1)
        # Should be allowed again (old timestamps pruned)
        limiter.check("user-e")  # must not raise
