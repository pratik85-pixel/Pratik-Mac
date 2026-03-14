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
    # ── daily_stress_summary ──────────────────────────────────────────────────
    with op.batch_alter_table("daily_stress_summary") as batch_op:
        batch_op.add_column(
            sa.Column("opening_balance", sa.Float(), nullable=True,
                      server_default=sa.text("0"))
        )
        batch_op.add_column(
            sa.Column("closing_balance", sa.Float(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("stress_pct_raw", sa.Float(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("recovery_pct_raw", sa.Float(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("ns_capacity_used", sa.Float(), nullable=True,
                      server_default=sa.text("0"))
        )

    # ── personal_model ────────────────────────────────────────────────────────
    with op.batch_alter_table("personal_model") as batch_op:
        batch_op.add_column(
            sa.Column("calibration_locked_at",
                      sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("personal_model") as batch_op:
        batch_op.drop_column("calibration_locked_at")

    with op.batch_alter_table("daily_stress_summary") as batch_op:
        batch_op.drop_column("ns_capacity_used")
        batch_op.drop_column("recovery_pct_raw")
        batch_op.drop_column("stress_pct_raw")
        batch_op.drop_column("closing_balance")
        batch_op.drop_column("opening_balance")
