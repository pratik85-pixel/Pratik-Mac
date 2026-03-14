"""Phase 10: continuous balance thread + calibration lock

Adds to daily_stress_summary:
  - opening_balance   FLOAT  (previous day's closing_balance carry-forward)
  - closing_balance   FLOAT  (net_balance at day close)
  - stress_pct_raw    FLOAT  (unbounded stress %, no clamp)
  - recovery_pct_raw  FLOAT  (unbounded recovery %, no clamp)
  - ns_capacity_used  FLOAT  (single symmetric denominator: (ceiling-floor)×960)

Adds to personal_model:
  - calibration_locked_at  TIMESTAMP WITH TIME ZONE  (when floor/ceiling/morning_avg froze)

Revision ID: a1b2c3d4e5f6
Revises: 957593d5ee14
Create Date: 2025-07-05
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision       = "a1b2c3d4e5f6"
down_revision  = "957593d5ee14"
branch_labels  = None
depends_on     = None


def upgrade() -> None:
    # ── daily_stress_summaries ────────────────────────────────────────────────
    op.add_column("daily_stress_summaries",
        sa.Column("opening_balance", sa.Float(), nullable=True,
                  server_default=sa.text("0")))
    op.add_column("daily_stress_summaries",
        sa.Column("closing_balance", sa.Float(), nullable=True))
    op.add_column("daily_stress_summaries",
        sa.Column("stress_pct_raw", sa.Float(), nullable=True))
    op.add_column("daily_stress_summaries",
        sa.Column("recovery_pct_raw", sa.Float(), nullable=True))
    op.add_column("daily_stress_summaries",
        sa.Column("ns_capacity_used", sa.Float(), nullable=True,
                  server_default=sa.text("0")))

    # ── personal_models ───────────────────────────────────────────────────────
    op.add_column("personal_models",
        sa.Column("calibration_locked_at",
                  sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("personal_models", "calibration_locked_at")
    op.drop_column("daily_stress_summaries", "ns_capacity_used")
    op.drop_column("daily_stress_summaries", "recovery_pct_raw")
    op.drop_column("daily_stress_summaries", "stress_pct_raw")
    op.drop_column("daily_stress_summaries", "closing_balance")
    op.drop_column("daily_stress_summaries", "opening_balance")
