"""Add yesterday summary cache fields to user unified profile.

Revision ID: 9c1f7f3a2d1b
Revises: v1w2x3y4z5a6
Create Date: 2026-04-01
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "9c1f7f3a2d1b"
down_revision = "v1w2x3y4z5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("user_unified_profiles") as batch:
        batch.add_column(sa.Column("yesterday_summary_weekly_trend", sa.Text(), nullable=True))
        batch.add_column(sa.Column("yesterday_summary_stress", sa.Text(), nullable=True))
        batch.add_column(sa.Column("yesterday_summary_recovery", sa.Text(), nullable=True))
        batch.add_column(sa.Column("yesterday_summary_adherence", sa.Text(), nullable=True))
        batch.add_column(sa.Column("yesterday_summary_generated_for", sa.Date(), nullable=True))
        batch.add_column(sa.Column("yesterday_summary_generated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("user_unified_profiles") as batch:
        batch.drop_column("yesterday_summary_generated_at")
        batch.drop_column("yesterday_summary_generated_for")
        batch.drop_column("yesterday_summary_adherence")
        batch.drop_column("yesterday_summary_recovery")
        batch.drop_column("yesterday_summary_stress")
        batch.drop_column("yesterday_summary_weekly_trend")

