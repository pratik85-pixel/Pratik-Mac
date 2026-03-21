"""band_wear_sessions

Revision ID: h3i4j5k6l7m8
Revises: g2h3i4j5k6l7
Create Date: 2026-03-21 00:00:00.000000

Creates the band_wear_sessions table.

Each row represents one continuous band wear period, bounded by either a
>90-minute gap in background windows (band-off close) or the end of time.
Stores final scores when closed, and the carry-forward opening_balance for
the current waking period within the session.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision      = 'h3i4j5k6l7m8'
down_revision = 'g2h3i4j5k6l7'
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.create_table(
        'band_wear_sessions',
        sa.Column('id',          postgresql.UUID(as_uuid=True), nullable=False,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id',     postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('started_at',  sa.DateTime(timezone=True), nullable=False),
        sa.Column('ended_at',    sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_closed',   sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('stress_pct',  sa.Float(), nullable=True),
        sa.Column('recovery_pct', sa.Float(), nullable=True),
        sa.Column('net_balance', sa.Float(), nullable=True),
        sa.Column('has_sleep_data', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('opening_balance', sa.Float(), nullable=False, server_default='0'),
        sa.Column('opening_balance_locked', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at',  sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at',  sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_band_wear_sessions_user_started',
        'band_wear_sessions', ['user_id', 'started_at'],
    )
    op.create_index(
        'ix_band_wear_sessions_user_open',
        'band_wear_sessions', ['user_id', 'is_closed'],
    )


def downgrade() -> None:
    op.drop_index('ix_band_wear_sessions_user_open',    table_name='band_wear_sessions')
    op.drop_index('ix_band_wear_sessions_user_started', table_name='band_wear_sessions')
    op.drop_table('band_wear_sessions')
