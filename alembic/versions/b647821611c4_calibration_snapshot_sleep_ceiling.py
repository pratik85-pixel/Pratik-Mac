"""calibration snapshot sleep ceiling

Revision ID: b647821611c4
Revises: v1w2x3y4z5a6
Create Date: 2026-04-01 04:42:56.470337+00:00

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b647821611c4'
down_revision: Union[str, None] = 'v1w2x3y4z5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "calibration_snapshots",
        sa.Column("rmssd_sleep_ceiling_clean", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("calibration_snapshots", "rmssd_sleep_ceiling_clean")
