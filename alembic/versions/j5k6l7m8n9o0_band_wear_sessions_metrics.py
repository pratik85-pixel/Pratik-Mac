"""band_wear_sessions: add pre-computed metric columns

Revision ID: j5k6l7m8n9o0
Revises: i4j5k6l7m8n9
Create Date: 2026-03-22

Adds five columns to band_wear_sessions that are computed at session close time:

  avg_rmssd_ms       — mean RMSSD (ms) over valid background-context windows
  avg_hr_bpm         — mean HR (bpm) over valid background-context windows
  sleep_rmssd_avg_ms — mean RMSSD (ms) over sleep-context windows
  sleep_started_at   — timestamp of first sleep-context window (window_start)
  sleep_ended_at     — timestamp of last sleep-context window (window_end)

All are nullable: they remain NULL for sessions with no valid signal data,
or (for sleep_*) for sessions without a sleep period.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision      = 'j5k6l7m8n9o0'
down_revision = 'i4j5k6l7m8n9'
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.add_column(
        'band_wear_sessions',
        sa.Column('avg_rmssd_ms', sa.Float(), nullable=True),
    )
    op.add_column(
        'band_wear_sessions',
        sa.Column('avg_hr_bpm', sa.Float(), nullable=True),
    )
    op.add_column(
        'band_wear_sessions',
        sa.Column('sleep_rmssd_avg_ms', sa.Float(), nullable=True),
    )
    op.add_column(
        'band_wear_sessions',
        sa.Column('sleep_started_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'band_wear_sessions',
        sa.Column('sleep_ended_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('band_wear_sessions', 'sleep_ended_at')
    op.drop_column('band_wear_sessions', 'sleep_started_at')
    op.drop_column('band_wear_sessions', 'sleep_rmssd_avg_ms')
    op.drop_column('band_wear_sessions', 'avg_hr_bpm')
    op.drop_column('band_wear_sessions', 'avg_rmssd_ms')
