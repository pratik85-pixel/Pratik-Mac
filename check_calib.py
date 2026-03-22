import asyncio
import sys
sys.path.insert(0, '.')
from api.config import get_settings
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

url = get_settings().DATABASE_URL

        # Schema discovery
        r_schema = await conn.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name='personal_models' ORDER BY ordinal_position"
        ))
        print('personal_models columns:', [r[0] for r in r_schema.fetchall()])

        r_schema2 = await conn.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name='calibration_snapshots' ORDER BY ordinal_position"
        ))
        print('calibration_snapshots columns:', [r[0] for r in r_schema2.fetchall()])

        r_users = await conn.execute(text("SELECT DISTINCT user_id FROM personal_models LIMIT 5"))
        print('personal_model user_ids:', [r[0] for r in r_users.fetchall()])

asyncio.run(main())
