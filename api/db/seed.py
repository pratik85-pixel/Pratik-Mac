"""
api/db/seed.py

Development seed data.

Usage (from project root):
    .venv/bin/python -m api.db.seed
"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from api.db.database import _get_engine
from api.db.schema import Base, User, UserHabits

# Stable dev user ID — used in tests and local dev
SEED_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


async def seed(db: AsyncSession) -> None:
    """
    Create tables (if absent) and insert a dev user with habits.
    Safe to run multiple times — uses merge to avoid duplicate keys.
    """
    # Ensure tables exist
    _engine, _ = _get_engine()
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    user = User(
        id=SEED_USER_ID,
        name="Dev User",
        email="dev@zenflow.local",
        training_level=1,
        onboarding={"completed": True, "goal": "stress_management"},
        archetype_primary="sympathetic_dominant",
        archetype_confidence={"sympathetic_dominant": 0.72},
    )
    await db.merge(user)

    habits = UserHabits(
        user_id=SEED_USER_ID,
        movement_enjoyed=["walking", "yoga"],
        exercise_frequency="3_4_times",
        alcohol="occasionally",
        caffeine="1_2_coffees",
        sleep_schedule="regular",
        typical_day="mostly_desk",
        stress_drivers=["work_pressure", "uncertainty"],
        decompress_via=["exercise", "nature"],
    )
    await db.merge(habits)

    await db.commit()
    print(f"[seed] dev user ready: {SEED_USER_ID}")


if __name__ == "__main__":
    async def _main() -> None:
        _, session_factory = _get_engine()
        async with session_factory() as db:
            await seed(db)

    asyncio.run(_main())
