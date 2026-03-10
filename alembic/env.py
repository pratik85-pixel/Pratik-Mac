"""
alembic/env.py

Alembic environment — configured for ZenFlow Verity.

Key choices:
- Uses DATABASE_SYNC_URL (psycopg2) for migrations so Alembic works
  synchronously, as it always has.
- Imports all ORM models via api.db.schema so --autogenerate detects
  every table in one pass.
- Reads config from api.config.get_settings() so .env overrides apply.
"""

from __future__ import annotations

import sys
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# ── Make project root importable ─────────────────────────────────────────────
# Alembic runs from the project root; add it to sys.path so `api.*` imports work.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Import all models so Alembic autogenerate sees them ──────────────────────
from api.db.schema import Base  # noqa: F401 — imports register all ORM models
import api.db.schema as _schema  # noqa: F401 — ensure all submodules are loaded

# ── Load app settings (picks up .env if present) ─────────────────────────────
from api.config import get_settings

_settings = get_settings()

# ── Alembic Config object (gives access to alembic.ini values) ───────────────
config = context.config

# Set sqlalchemy.url from our settings — overrides blank value in alembic.ini
config.set_main_option("sqlalchemy.url", _settings.DATABASE_SYNC_URL)

# Interpret the config file for Python logging if present
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata for --autogenerate support
target_metadata = Base.metadata


# ── Offline mode ──────────────────────────────────────────────────────────────
def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode (emit SQL to stdout without a DB
    connection). Useful for generating migration scripts for review.

        alembic upgrade head --sql
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


# ── Online mode ───────────────────────────────────────────────────────────────
def run_migrations_online() -> None:
    """
    Run migrations against a live database connection.
    Uses psycopg2 (sync) driver — Alembic does not need asyncpg.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
