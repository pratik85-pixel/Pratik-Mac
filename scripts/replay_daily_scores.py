"""replay_daily_scores.py

Backfill / refresh DailyStressSummary rows for all users and dates that
have background-window data but whose live score has either never been
materialised or is still marked partial (is_partial_data=True).

Rows already finalised (is_partial_data=False) are left untouched —
close_day() is authoritative for those.

Usage
-----
    python3 scripts/replay_daily_scores.py [--user <uuid>] [--dry-run]

Options
-------
    --user <uuid>   Replay only this user (repeatable).
    --dry-run       Print what would be computed without writing to DB.
"""

import asyncio
import argparse
import logging
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta, date

# Make sure project root is on the path.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from api.config import get_settings
import api.db.schema as db
from api.services.tracking_service import TrackingService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger("replay")

UTC = timezone.utc


async def _get_distinct_user_dates(session: AsyncSession, user_ids: list | None):
    """Return list of (user_id, calendar_date) with at least one background window."""
    q = text("""
        SELECT DISTINCT
            user_id::text,
            date_trunc('day', window_start AT TIME ZONE 'UTC')::date AS cal_date
        FROM background_windows
        ORDER BY 1, 2
    """)
    result = await session.execute(q)
    rows = result.fetchall()
    if user_ids is not None:
        filter_set = {u.lower() for u in user_ids}
        rows = [r for r in rows if r[0].lower() in filter_set]
    return rows


async def replay(user_filter: list[str] | None = None, dry_run: bool = False) -> None:
    db_url = get_settings().DATABASE_URL
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(db_url, echo=False, pool_size=2, max_overflow=0)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSessionLocal() as session:
        rows = await _get_distinct_user_dates(session, user_filter)

    logger.info("Found %d (user, date) combinations with window data.", len(rows))

    skipped_finalised = 0
    replayed          = 0
    errors            = 0

    for user_id_str, cal_date in rows:
        import uuid as _uuid_mod
        user_uuid = _uuid_mod.UUID(user_id_str)

        async with AsyncSessionLocal() as session:
            # Check if row is already finalised.
            day_start = datetime(cal_date.year, cal_date.month, cal_date.day, tzinfo=UTC)
            day_end   = day_start + timedelta(days=1)
            existing_res = await session.execute(
                select(db.DailyStressSummary)
                .where(db.DailyStressSummary.user_id == user_uuid)
                .where(db.DailyStressSummary.summary_date >= day_start)
                .where(db.DailyStressSummary.summary_date < day_end)
                .limit(1)
            )
            existing = existing_res.scalar_one_or_none()

            if existing is not None and not existing.is_partial_data:
                skipped_finalised += 1
                logger.debug("SKIP finalised  user=%s date=%s", user_id_str, cal_date)
                continue

            if dry_run:
                logger.info("DRY-RUN  user=%s date=%s", user_id_str, cal_date)
                replayed += 1
                continue

            try:
                svc  = TrackingService(session, user_uuid)
                live = await svc.compute_live_summary(cal_date)
                if live is None:
                    logger.warning("No data    user=%s date=%s — skipping", user_id_str, cal_date)
                    continue

                if existing is None:
                    row = db.DailyStressSummary(
                        user_id      = user_uuid,
                        summary_date = day_start,
                    )
                    session.add(row)
                else:
                    row = existing

                row.stress_load_score         = live.stress_load_score
                row.day_type                  = live.day_type
                row.raw_suppression_area      = live.raw_suppression_area
                row.raw_recovery_area_sleep   = live.raw_recovery_area_sleep
                row.raw_recovery_area_zenflow = live.raw_recovery_area_zenflow
                row.raw_recovery_area_daytime = live.raw_recovery_area_daytime
                row.raw_recovery_area_waking  = live.raw_recovery_area_waking
                row.max_possible_suppression  = live.max_possible_suppression
                row.is_estimated              = live.is_estimated
                row.is_partial_data           = True
                row.waking_recovery_score     = live.waking_recovery_score
                row.sleep_recovery_score      = live.sleep_recovery_score
                row.net_balance               = live.net_balance
                row.opening_balance           = live.opening_balance
                row.opening_recovery          = live.opening_recovery
                row.opening_stress            = live.opening_stress
                row.closing_balance           = live.closing_balance
                row.ns_capacity_used          = live.ns_capacity_used
                row.stress_pct_raw            = live.stress_pct_raw
                row.recovery_pct_raw          = live.recovery_pct_raw
                row.ns_capacity_recovery      = live.ns_capacity_recovery_used

                await svc._assign_readiness_for_row(row)

                await session.commit()
                logger.info("Replayed   user=%s date=%s net=%.1f",
                            user_id_str, cal_date, live.net_balance or 0.0)
                replayed += 1
            except Exception as exc:
                await session.rollback()
                logger.error("ERROR      user=%s date=%s  %s", user_id_str, cal_date, exc)
                errors += 1

    await engine.dispose()

    logger.info("Done.  replayed=%d  skipped_finalised=%d  errors=%d",
                replayed, skipped_finalised, errors)


def _parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--user", metavar="UUID", action="append", dest="users",
                   help="Limit replay to this user UUID (repeatable).")
    p.add_argument("--dry-run", action="store_true",
                   help="Print what would be computed without writing.")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(replay(user_filter=args.users, dry_run=args.dry_run))
