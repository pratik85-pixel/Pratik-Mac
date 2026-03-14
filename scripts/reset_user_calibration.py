#!/usr/bin/env python3
"""
scripts/reset_user_calibration.py

Surgically reset a user's calibration state while preserving all raw
beat data (BackgroundWindows, StressWindows, RecoveryWindows).

This lets the scoring model re-learn the baseline cleanly after the
Phase 10 architecture changes — without losing any raw signal history.

What is DELETED:
  - personal_model row  (floor / ceiling / morning_avg / lock)
  - daily_stress_summary rows  (all computed scores for this user)
  - capacity_snapshot rows  (baseline version history)

What is KEPT (raw signal, can be replayed):
  - background_windows
  - stress_windows
  - recovery_windows
  - user row itself

Usage:
    DB_URL="postgresql://..." python scripts/reset_user_calibration.py <user_id>
    DB_URL="postgresql://..." python scripts/reset_user_calibration.py <user_id> --confirm
"""

import asyncio
import os
import sys
import uuid

DATABASE_URL = os.environ.get("DB_URL") or os.environ.get("DATABASE_URL")


def _require_db_url() -> str:
    if not DATABASE_URL:
        print("ERROR: set DB_URL or DATABASE_URL env variable.")
        sys.exit(1)
    return DATABASE_URL


async def preview(uid: uuid.UUID) -> None:
    """Print counts of what *would* be deleted."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import select, func, text

    url = _require_db_url().replace("postgresql://", "postgresql+asyncpg://")
    engine = create_async_engine(url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        tables = {
            "personal_model":       "user_id",
            "daily_stress_summary": "user_id",
            "capacity_snapshot":    "user_id",
        }
        print(f"\n── Calibration data for user {uid} ──")
        for table, col in tables.items():
            result = await session.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE {col} = :uid"), {"uid": str(uid)}
            )
            count = result.scalar()
            print(f"  {table:<30} {count} row(s) would be deleted")

        # Kept data
        kept_tables = {
            "background_windows": "user_id",
            "stress_windows":     "user_id",
            "recovery_windows":   "user_id",
        }
        print(f"\n── Raw data that will be KEPT ──")
        for table, col in kept_tables.items():
            result = await session.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE {col} = :uid"), {"uid": str(uid)}
            )
            count = result.scalar()
            print(f"  {table:<30} {count} row(s) preserved")

    await engine.dispose()


async def reset(uid: uuid.UUID) -> None:
    """Actually delete calibration rows."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import text

    url = _require_db_url().replace("postgresql://", "postgresql+asyncpg://")
    engine = create_async_engine(url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        async with session.begin():
            # Order matters: child tables first (FK constraints)
            await session.execute(
                text("DELETE FROM capacity_snapshot WHERE user_id = :uid"), {"uid": str(uid)}
            )
            await session.execute(
                text("DELETE FROM daily_stress_summary WHERE user_id = :uid"), {"uid": str(uid)}
            )
            await session.execute(
                text("DELETE FROM personal_model WHERE user_id = :uid"), {"uid": str(uid)}
            )
        print(f"\n✓ Calibration reset for user {uid}.")
        print("  The model will rebuild from scratch on next data ingest.")
        print("  Raw background/stress/recovery windows were NOT touched.")

    await engine.dispose()


def main() -> None:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)

    user_id_str   = args[0]
    confirmed     = "--confirm" in args

    try:
        uid = uuid.UUID(user_id_str)
    except ValueError:
        print(f"ERROR: '{user_id_str}' is not a valid UUID.")
        sys.exit(1)

    # Always show preview first
    asyncio.run(preview(uid))

    if not confirmed:
        print(
            "\nDRY RUN — no changes made.\n"
            "Re-run with --confirm to apply:\n"
            f"  python scripts/reset_user_calibration.py {uid} --confirm"
        )
        sys.exit(0)

    # Double-check
    answer = input("\nType 'yes' to proceed with deletion: ").strip().lower()
    if answer != "yes":
        print("Aborted.")
        sys.exit(0)

    asyncio.run(reset(uid))


if __name__ == "__main__":
    main()
