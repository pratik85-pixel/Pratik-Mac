"""band_wear_sessions: add wake_locked_at column

Revision ID: i4j5k6l7m8n9
Revises: h3i4j5k6l7m8
Create Date: 2026-03-21

Adds wake_locked_at (nullable timestamptz) to band_wear_sessions.
This column records the exact timestamp of the first sleep→background context
transition within a session (i.e. when opening_balance was locked).

_compute_session_summary uses this as the window-query lower bound when set,
so post-wake stress/recovery scoring begins at wake_locked_at instead of
session_start — preventing the pre-wake period from being double-counted
alongside opening_balance.
"""
from alembic import op
import sqlalchemy as sa

revision = 'i4j5k6l7m8n9'
down_revision = 'h3i4j5k6l7m8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'band_wear_sessions',
        sa.Column('wake_locked_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('band_wear_sessions', 'wake_locked_at')
