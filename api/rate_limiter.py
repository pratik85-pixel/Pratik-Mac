"""
api/rate_limiter.py

In-process per-user rolling window rate limiter.
No external dependencies — stdlib collections.deque only.
State resets on process restart (acceptable for a native health app).
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, UTC

from fastapi import HTTPException


class RollingRateLimiter:
    """Per-key rolling window rate limiter (stdlib only, no Redis)."""

    def __init__(self, max_calls: int, window_seconds: int) -> None:
        self._max_calls = max_calls
        self._window_seconds = window_seconds
        self._records: dict[str, deque[float]] = {}

    def check(self, key: str) -> None:
        """
        Record a call for *key*.  Raises HTTP 429 if the key has exceeded
        max_calls within the rolling window.  No-op (records call) on success.
        """
        now = datetime.now(UTC).timestamp()
        cutoff = now - self._window_seconds
        dq = self._records.setdefault(key, deque())
        # Purge timestamps older than the window
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= self._max_calls:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Rate limit exceeded — max {self._max_calls} requests "
                    f"per {self._window_seconds}s. Please slow down."
                ),
            )
        dq.append(now)


# ── Shared singletons — one instance per process ──────────────────────────────
from api.config import get_settings as _get_settings

_cfg = _get_settings()

# conversation: 10 turns per user per 60 s  (normal usage: 1–3 per session)
conversation_limiter: RollingRateLimiter = RollingRateLimiter(max_calls=10, window_seconds=60)
# ingest: 20 batches per user per 60 s  (normal: ~1 per 5 min from the band)
ingest_limiter: RollingRateLimiter = RollingRateLimiter(max_calls=20, window_seconds=60)

# Shared LLM bucket — every coach endpoint that invokes the LLM charges
# against the same per-user counter so an attacker cannot fan-out across
# endpoints to drain credit.  Defaults: 30 LLM requests per 60 s per user.
llm_unit_limiter: RollingRateLimiter = RollingRateLimiter(
    max_calls=_cfg.LLM_RATE_MAX_CALLS,
    window_seconds=_cfg.LLM_RATE_WINDOW_SECONDS,
)

# WebSocket connections per user — guards against runaway reconnect loops.
ws_conn_limiter: RollingRateLimiter = RollingRateLimiter(max_calls=10, window_seconds=60)
