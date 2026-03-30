"""add user push token fields

Revision ID: q6r7s8t9u0v1
Revises: p1q2r3s4t5u6
Create Date: 2026-03-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "q6r7s8t9u0v1"
down_revision = "p1q2r3s4t5u6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("push_token", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("push_platform", sa.String(length=20), nullable=True))
    op.add_column("users", sa.Column("push_token_updated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "push_token_updated_at")
    op.drop_column("users", "push_platform")
    op.drop_column("users", "push_token")
