"""users: last_morning_cycle_reset_local_date for nap-safe morning reset

Revision ID: n0o1p2q3r4s5
Revises: m9n0o1p2q3r4
Create Date: 2026-03-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "n0o1p2q3r4s5"
down_revision = "m9n0o1p2q3r4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("last_morning_cycle_reset_local_date", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "last_morning_cycle_reset_local_date")
