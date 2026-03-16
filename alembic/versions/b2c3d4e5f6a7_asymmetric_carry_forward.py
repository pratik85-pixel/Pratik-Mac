"""Asymmetric carry-forward: split opening_balance into opening_recovery + opening_stress

Adds to daily_stress_summaries:
  - opening_recovery  FLOAT  nullable  — max(0, prev closing_balance): prior surplus
  - opening_stress    FLOAT  nullable  — min(0, prev closing_balance): prior debt (stored ≤ 0)

These columns let the coach and UI surface the direction of the carry-forward
explicitly ("you're carrying +12 recovery surplus" vs "you have -8 stress debt")
rather than collapsing it to a single ambiguous scalar.

The net_balance formula is unchanged:
    net_balance = recovery_pct_raw - stress_pct_raw + opening_balance
where opening_balance = opening_recovery + opening_stress always holds.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-15
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision      = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.add_column("daily_stress_summaries",
        sa.Column("opening_recovery", sa.Float(), nullable=True))
    op.add_column("daily_stress_summaries",
        sa.Column("opening_stress", sa.Float(), nullable=True))

    # Back-fill existing rows from opening_balance so the split is consistent
    # with the new invariant (opening_recovery + opening_stress = opening_balance).
    op.execute("""
        UPDATE daily_stress_summaries
        SET
            opening_recovery = GREATEST(opening_balance, 0),
            opening_stress   = LEAST(opening_balance, 0)
        WHERE opening_balance IS NOT NULL
    """)


def downgrade() -> None:
    op.drop_column("daily_stress_summaries", "opening_stress")
    op.drop_column("daily_stress_summaries", "opening_recovery")
