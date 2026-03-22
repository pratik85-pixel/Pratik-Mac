"""Sleep scoring v2 — sleep RMSSD baseline + split recovery denominator audit

Adds:
  personal_models.rmssd_sleep_avg          — personal median sleep RMSSD (from calibration)
  personal_models.rmssd_sleep_ceiling      — P90 sleep RMSSD (cap extreme REM spikes)
  calibration_snapshots.rmssd_sleep_avg_clean — sleep avg computed on each calibration day
  calibration_snapshots.sleep_windows_count   — how many sleep windows fed the calc
  daily_stress_summaries.ns_capacity_recovery — audit: denominator used for recovery score

Revision ID: f1a2b3c4d5e6
Revises: d1e2f3a4b5c6
Create Date: 2026-03-17
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision      = "f1a2b3c4d5e6"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    # ── personal_models ───────────────────────────────────────────────────────
    op.add_column(
        "personal_models",
        sa.Column("rmssd_sleep_avg", sa.Float(), nullable=True),
    )
    op.add_column(
        "personal_models",
        sa.Column("rmssd_sleep_ceiling", sa.Float(), nullable=True),
    )

    # ── calibration_snapshots ────────────────────────────────────────────────
    op.add_column(
        "calibration_snapshots",
        sa.Column("rmssd_sleep_avg_clean", sa.Float(), nullable=True),
    )
    op.add_column(
        "calibration_snapshots",
        sa.Column("sleep_windows_count", sa.Integer(), nullable=True),
    )

    # ── daily_stress_summaries ───────────────────────────────────────────────
    op.add_column(
        "daily_stress_summaries",
        sa.Column("ns_capacity_recovery", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("daily_stress_summaries", "ns_capacity_recovery")
    op.drop_column("calibration_snapshots", "sleep_windows_count")
    op.drop_column("calibration_snapshots", "rmssd_sleep_avg_clean")
    op.drop_column("personal_models", "rmssd_sleep_ceiling")
    op.drop_column("personal_models", "rmssd_sleep_avg")
