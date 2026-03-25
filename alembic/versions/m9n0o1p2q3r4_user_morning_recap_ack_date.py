"""users: morning_recap_ack_for_date for Phase 5 morning recap card

Revision ID: m9n0o1p2q3r4
Revises: k6l7m8n9o0p1
Create Date: 2026-03-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "m9n0o1p2q3r4"
down_revision = "k6l7m8n9o0p1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("morning_recap_ack_for_date", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "morning_recap_ack_for_date")
