"""materialised_score_updated_at

Revision ID: g2h3i4j5k6l7
Revises: f1a2b3c4d5e6
Create Date: 2026-03-19 00:00:00.000000

Adds an updated_at column to daily_stress_summaries so the UI can tell
when a live (materialised) row was last refreshed without querying the
full row.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision    = 'g2h3i4j5k6l7'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.add_column(
        'daily_stress_summaries',
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column('daily_stress_summaries', 'updated_at')
