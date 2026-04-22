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
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

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
    # Comma-separated list of allowed origins (e.g. "https://app.example.com,https://admin.example.com").
    # Native mobile apps don't send an Origin header, so the default of [] is safe for them.
    # Setting CORS_ORIGINS="*" is only honoured when DEBUG=true (see model_validator below).
    CORS_ORIGINS: list[str] = []
    # Trusted reverse-proxy hosts (Host header allowlist). Empty disables the check.
    TRUSTED_HOSTS: list[str] = []
    DEBUG: bool = False
    # `dev` | `staging` | `production` — used to gate security defaults.
    ENVIRONMENT: str = "production"

    # ── Feature flags ──────────────────────────────────────────────────────────
    ENABLE_WEBSOCKET: bool = True
    ENABLE_CONVERSATION: bool = True
    ENABLE_ADMIN_ENDPOINTS: bool = False
    ADMIN_API_KEY: str = ""
    # Default ON in production — the fallback X-User-Id path is for tests/dev only.
    ENABLE_JWT_AUTH: bool = False
    # When True, trust the `X-User-Id` header path (dev only). Forced False in production.
    ALLOW_HEADER_AUTH: bool = True
    JWT_ISSUER: str = ""
    JWT_AUDIENCE: str = ""
    JWT_JWKS_URL: str = ""
    JWT_LEEWAY_SECONDS: int = 60

    # ── LLM rate limiting (per-user buckets shared across LLM endpoints) ──────
    LLM_RATE_MAX_CALLS: int = 30        # max LLM-touching requests
    LLM_RATE_WINDOW_SECONDS: int = 60   # per window

    # ── Live-session processing windows ───────────────────────────────────────
    WINDOW_SECONDS: int = 60          # coherence analysis window duration
    WINDOW_OVERLAP_SECONDS: int = 30  # overlap between consecutive windows
    MIN_BEATS_PER_WINDOW: int = 30    # skip window if fewer beats accumulated

    @field_validator("CORS_ORIGINS", "TRUSTED_HOSTS", mode="before")
    @classmethod
    def _split_list(cls, v: object) -> list[str]:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v  # type: ignore[return-value]

    @model_validator(mode="after")
    def _enforce_production_defaults(self) -> "Settings":
        """
        Harden insecure defaults when running outside of development.

        - Disallow `CORS_ORIGINS=["*"]` + credentials in production.
        - Disable the `X-User-Id` header-auth fallback unless DEBUG is true
          (JWT is required in production).
        """
        env = (self.ENVIRONMENT or "").lower()
        is_dev = env in {"dev", "development", "local"} or self.DEBUG
        if not is_dev:
            if self.CORS_ORIGINS == ["*"]:
                # Silently drop unsafe wildcard in prod — caller must set an allowlist.
                self.CORS_ORIGINS = []
            # Force header-auth off in production so JWT becomes the only path.
            if self.ALLOW_HEADER_AUTH and self.ENABLE_JWT_AUTH:
                self.ALLOW_HEADER_AUTH = False
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton Settings instance (cached after first call)."""
    return Settings()
