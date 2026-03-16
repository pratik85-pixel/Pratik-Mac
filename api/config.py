"""
api/config.py

Central configuration for the ZenFlow Verity API.
Loads from environment / .env file via pydantic-settings.

All downstream code should call `get_settings()` (LRU-cached) rather
than instantiating Settings directly.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Database ───────────────────────────────────────────────────────────────
    # Railway provides DATABASE_URL as postgresql://... (no driver prefix).
    # The validators below normalise it to the correct driver-prefixed forms.
    DATABASE_URL: str = (
        "postgresql+asyncpg://zenflow:zenflow@localhost:5432/zenflow_dev"
    )
    DATABASE_SYNC_URL: str = (
        "postgresql+psycopg2://zenflow:zenflow@localhost:5432/zenflow_dev"
    )

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def _fix_async_url(cls, v: str) -> str:
        """Ensure DATABASE_URL uses the asyncpg driver."""
        v = str(v)
        if v.startswith("postgresql://") or v.startswith("postgres://"):
            v = "postgresql+asyncpg://" + v.split("://", 1)[1]
        return v

    @field_validator("DATABASE_SYNC_URL", mode="before")
    @classmethod
    def _fix_sync_url(cls, v: str) -> str:
        """Ensure DATABASE_SYNC_URL uses the psycopg2 driver."""
        v = str(v)
        if v.startswith("postgresql://") or v.startswith("postgres://"):
            v = "postgresql+psycopg2://" + v.split("://", 1)[1]
        return v

    @model_validator(mode="after")
    def _derive_sync_url(self) -> "Settings":
        """
        If only DATABASE_URL was set (Railway pattern), derive DATABASE_SYNC_URL
        automatically so Alembic migrations work without an extra env var.
        """
        if "asyncpg" in self.DATABASE_URL and "localhost" in self.DATABASE_SYNC_URL:
            self.DATABASE_SYNC_URL = self.DATABASE_URL.replace(
                "postgresql+asyncpg://", "postgresql+psycopg2://"
            )
        return self

    # ── LLM ──────────────────────────────────────────────────────────────────
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o"
    # False → always use local_engine (offline / test mode)
    LLM_ENABLED: bool = False

    # ── Server / CORS ─────────────────────────────────────────────────────────
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    # Native mobile apps don't send an Origin header — ["*"] is safe here.
    CORS_ORIGINS: list[str] = ["*"]
    DEBUG: bool = False

    # ── Feature flags ──────────────────────────────────────────────────────────
    ENABLE_WEBSOCKET: bool = True
    ENABLE_CONVERSATION: bool = True

    # ── Live-session processing windows ───────────────────────────────────────
    WINDOW_SECONDS: int = 60          # coherence analysis window duration
    WINDOW_OVERLAP_SECONDS: int = 30  # overlap between consecutive windows
    MIN_BEATS_PER_WINDOW: int = 30    # skip window if fewer beats accumulated

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> list[str]:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v  # type: ignore[return-value]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton Settings instance (cached after first call)."""
    return Settings()
