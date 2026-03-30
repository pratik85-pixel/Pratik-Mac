"""enforce unique notification dedupe per user

Revision ID: r7s8t9u0v1w2
Revises: q6r7s8t9u0v1
Create Date: 2026-03-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "r7s8t9u0v1w2"
down_revision = "q6r7s8t9u0v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep the newest row for each (user_id, dedupe_key) pair, drop older duplicates.
    op.execute(
        """
        DELETE FROM notification_events ne
        USING (
            SELECT id
            FROM (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY user_id, dedupe_key
                        ORDER BY created_at DESC, id DESC
                    ) AS rn
                FROM notification_events
                WHERE dedupe_key IS NOT NULL
            ) ranked
            WHERE ranked.rn > 1
        ) d
        WHERE ne.id = d.id
        """
    )
    op.create_index(
        "uq_notification_events_user_dedupe_key",
        "notification_events",
        ["user_id", "dedupe_key"],
        unique=True,
        postgresql_where=sa.text("dedupe_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_notification_events_user_dedupe_key", table_name="notification_events")
