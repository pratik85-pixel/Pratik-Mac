import asyncio
import sys
sys.path.insert(0, '.')
from api.config import get_settings
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

url = get_settings().DATABASE_URL


async def main():
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        r = await conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='personal_models' ORDER BY ordinal_position"
        ))
        print('personal_models columns:', [row[0] for row in r.fetchall()])

        r2 = await conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='calibration_snapshots' ORDER BY ordinal_position"
        ))
        print('calibration_snapshots columns:', [row[0] for row in r2.fetchall()])

        r3 = await conn.execute(text("SELECT user_id FROM personal_models LIMIT 5"))
        print('personal_model user_ids:', [row[0] for row in r3.fetchall()])


asyncio.run(main())
