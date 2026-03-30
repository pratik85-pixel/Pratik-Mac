"""personal_models.rmssd_resting_hr_bpm for Phase 2 stress HR gate

Revision ID: t8u9v0w1x2y3
Revises: r7s8t9u0v1w2
Create Date: 2026-03-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "t8u9v0w1x2y3"
down_revision = "r7s8t9u0v1w2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "personal_models",
        sa.Column("rmssd_resting_hr_bpm", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("personal_models", "rmssd_resting_hr_bpm")
