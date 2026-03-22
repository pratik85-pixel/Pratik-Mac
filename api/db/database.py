"""
api/db/database.py

Async SQLAlchemy engine, session factory, and FastAPI dependency.

Usage in routers
----------------
    from api.db.database import get_db
    from sqlalchemy.ext.asyncio import AsyncSession

    @router.get("/example")
    async def handler(db: AsyncSession = Depends(get_db)):
        ...
"""

from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from api.config import get_settings

_cfg = get_settings()

# Engine and session factory are created lazily so that importing this module
# does not require the asyncpg driver at collection time (e.g. during testing).
_engine = None
_AsyncSessionLocal = None


def _get_engine():
    global _engine, _AsyncSessionLocal
    if _engine is None:
        _engine = create_async_engine(
            _cfg.DATABASE_URL,
            echo=_cfg.DEBUG,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
        )
        _AsyncSessionLocal = async_sessionmaker(
            bind=_engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )
    return _engine, _AsyncSessionLocal


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that yields an AsyncSession per request.
    Rolls back on error; always closes the session.
    """
    _, session_factory = _get_engine()
    async with session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


class _SessionLocalProxy:
    """
    Public proxy for the lazily-initialised session factory.
    Supports `async with AsyncSessionLocal() as session:` — the same pattern
    used throughout nightly_rebuild.py and any other non-FastAPI callers.
    """
    def __call__(self):
        _, factory = _get_engine()
        return factory()


AsyncSessionLocal = _SessionLocalProxy()
