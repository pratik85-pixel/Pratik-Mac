"""
Request-scoped lightweight metrics helpers.

This module keeps per-request counters in contextvars so middleware and DB hooks
can record baseline performance without introducing external dependencies.
"""

from __future__ import annotations

from contextvars import ContextVar

_request_query_count: ContextVar[int] = ContextVar("request_query_count", default=0)


def reset_request_metrics() -> None:
    """Reset request-local counters at request start."""
    _request_query_count.set(0)


def incr_db_query_count() -> None:
    """Increment request-local DB query count."""
    _request_query_count.set(_request_query_count.get() + 1)


def get_db_query_count() -> int:
    """Return DB query count for the current request context."""
    return _request_query_count.get()
