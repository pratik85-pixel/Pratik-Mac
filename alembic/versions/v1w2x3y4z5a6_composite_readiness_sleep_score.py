"""composite readiness + sleep_recovery_score on daily_stress_summaries

Revision ID: v1w2x3y4z5a6
Revises: u9v0w1x2y3z4
Create Date: 2026-03-30

- Adds sleep_recovery_score (persisted display metric from daily summarizer).
- Documents readiness_score column: composite 0–100 from prior-day metrics
  (not the deprecated net-balance proxy).
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "v1w2x3y4z5a6"
down_revision = "u9v0w1x2y3z4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "daily_stress_summaries",
        sa.Column("sleep_recovery_score", sa.Float(), nullable=True),
    )
    op.execute(
        """
        COMMENT ON COLUMN daily_stress_summaries.readiness_score IS
        'Composite 0-100 readiness for this calendar morning: 0.40*waking + 0.35*sleep - 0.25*stress_penalty from prior day (see plan_readiness_contract).';
        """
    )


def downgrade() -> None:
    op.execute(
        "COMMENT ON COLUMN daily_stress_summaries.readiness_score IS NULL;"
    )
    op.drop_column("daily_stress_summaries", "sleep_recovery_score")
