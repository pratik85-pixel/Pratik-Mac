"""Split yesterday_summary_recovery into waking + sleep recovery fields.

Revision ID: yd1x3w2e9a8b
Revises: w2x3y4z5a6b7
Create Date: 2026-04-22

Adds two new text columns on `user_unified_profiles` so the Layer 3
yesterday-summary output can carry independent narratives for waking
recovery and sleep recovery (the coach previously returned a single
combined `yesterday_summary_recovery` field).

The existing `yesterday_summary_recovery` column is kept for backward
compatibility (historical rows / mid-rollout reads) but new writes
populate the two split columns instead.
"""
from alembic import op
import sqlalchemy as sa


revision = "yd1x3w2e9a8b"
down_revision = "w2x3y4z5a6b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("user_unified_profiles") as batch:
        batch.add_column(
            sa.Column("yesterday_summary_waking_recovery", sa.Text(), nullable=True)
        )
        batch.add_column(
            sa.Column("yesterday_summary_sleep_recovery", sa.Text(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("user_unified_profiles") as batch:
        batch.drop_column("yesterday_summary_sleep_recovery")
        batch.drop_column("yesterday_summary_waking_recovery")
