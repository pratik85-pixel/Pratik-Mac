"""Add capacity_growth_streak to personal_models

Tracks how many consecutive days the user's live RMSSD high-water mark has
exceeded their locked calibration ceiling by >CAPACITY_GROWTH_THRESHOLD_PCT.
When this streak reaches CAPACITY_GROWTH_CONFIRM_DAYS (7), the nightly rebuild
triggers a capacity re-lock: rmssd_ceiling updates, capacity_version increments,
a ModelSnapshot is written.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-03-16
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision      = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.add_column(
        "personal_models",
        sa.Column("capacity_growth_streak", sa.Integer(), nullable=True, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("personal_models", "capacity_growth_streak")
