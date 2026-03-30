"""Add coach_narrative_date and plan_brief_text to user_unified_profiles

Revision ID: u9v0w1x2y3z4
Revises: t8u9v0w1x2y3
Create Date: 2026-03-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "u9v0w1x2y3z4"
down_revision = "t8u9v0w1x2y3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_unified_profiles",
        sa.Column("coach_narrative_date", sa.Date(), nullable=True),
    )
    op.add_column(
        "user_unified_profiles",
        sa.Column("plan_brief_text", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_unified_profiles", "plan_brief_text")
    op.drop_column("user_unified_profiles", "coach_narrative_date")
