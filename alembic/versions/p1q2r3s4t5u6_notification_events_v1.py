"""notification events/actions tables for v1 feed

Revision ID: p1q2r3s4t5u6
Revises: n0o1p2q3r4s5
Create Date: 2026-03-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "p1q2r3s4t5u6"
down_revision = "n0o1p2q3r4s5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column("priority", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("requires_action", sa.Boolean(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("deeplink", sa.String(length=500), nullable=True),
        sa.Column("dedupe_key", sa.String(length=255), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notification_events_user_created", "notification_events", ["user_id", "created_at"])
    op.create_index("ix_notification_events_user_status", "notification_events", ["user_id", "status"])
    op.create_index("ix_notification_events_dedupe_key", "notification_events", ["dedupe_key"])

    op.create_table(
        "notification_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("notification_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action_type", sa.String(length=30), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["notification_id"], ["notification_events.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_notification_actions_user_idempotency"),
    )
    op.create_index("ix_notification_actions_user_created", "notification_actions", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_notification_actions_user_created", table_name="notification_actions")
    op.drop_table("notification_actions")

    op.drop_index("ix_notification_events_dedupe_key", table_name="notification_events")
    op.drop_index("ix_notification_events_user_status", table_name="notification_events")
    op.drop_index("ix_notification_events_user_created", table_name="notification_events")
    op.drop_table("notification_events")
