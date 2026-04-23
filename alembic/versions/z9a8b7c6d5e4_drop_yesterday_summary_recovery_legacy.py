"""Drop legacy yesterday_summary_recovery (split fields are canonical).

Revision ID: z9a8b7c6d5e4
Revises: yd1x3w2e9a8b
Create Date: 2026-04-22

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "z9a8b7c6d5e4"
down_revision = "yd1x3w2e9a8b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("user_unified_profiles") as batch:
        batch.drop_column("yesterday_summary_recovery")


def downgrade() -> None:
    with op.batch_alter_table("user_unified_profiles") as batch:
        batch.add_column(sa.Column("yesterday_summary_recovery", sa.Text(), nullable=True))
