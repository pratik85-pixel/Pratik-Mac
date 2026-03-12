import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from api.db.schema import ActivityCatalog
from api.db.database import _get_engine
from tagging.activity_catalog import _CATALOG

async def seed_activity_catalog():
    _, AsyncSessionLocal = _get_engine()
    async with AsyncSessionLocal() as session:
        for activity in _CATALOG:
            # Check if it exists
            db_activity = await session.get(ActivityCatalog, activity.slug)
            if not db_activity:
                db_activity = ActivityCatalog(
                    slug=activity.slug,
                    name=activity.display_name,
                    category=activity.category,
                    intensity=activity.stress_or_recovery,
                    icon=":)",
                    description=""
                )
                session.add(db_activity)
        await session.commit()
    print("Seeded ActivityCatalog successfully.")

if __name__ == "__main__":
    asyncio.run(seed_activity_catalog())
