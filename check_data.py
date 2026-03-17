import asyncio, sys
sys.path.insert(0, '/Users/pratikbarman/Desktop/Zenflow_backend')
from api.db.database import _get_engine
from sqlalchemy import text

UID = '2420112a-d69c-4938-972a-6598cc8526af'

async def check():
    eng, _ = _get_engine()
    async with eng.connect() as conn:
        r = await conn.execute(text('SELECT COUNT(*), MAX(window_end) FROM background_windows WHERE user_id = :u'), {'u': UID})
        print('background_windows (count, latest):', r.fetchone())

        r = await conn.execute(text('SELECT COUNT(*), MAX(summary_date) FROM daily_stress_summaries WHERE user_id = :u'), {'u': UID})
        print('daily_summaries (count, latest):', r.fetchone())

        r = await conn.execute(text('SELECT window_start, window_end, rmssd_ms FROM background_windows WHERE user_id = :u ORDER BY window_end DESC LIMIT 5'), {'u': UID})
        print('Latest bg windows:')
        for row in r.fetchall():
            print(' ', row)

asyncio.run(check())
