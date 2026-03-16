"""Add calibration_snapshots table

Audit table written by _run_calibration_batch() at each day-close during
the 3-day calibration window. Records raw vs clean RMSSD values, filter
stats, and whether the batch was committed to personal_model.

Revision ID: d1e2f3a4b5c6
Revises: c3d4e5f6a7b8
Create Date: 2026-03-16
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision      = "d1e2f3a4b5c6"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.create_table(
        "calibration_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("day_number", sa.Integer(), nullable=False),
        # Raw (before artifact filter)
        sa.Column("rmssd_floor_raw",       sa.Float(), nullable=True),
        sa.Column("rmssd_ceiling_raw",     sa.Float(), nullable=True),
        sa.Column("rmssd_morning_avg_raw", sa.Float(), nullable=True),
        # Clean (after artifact filter)
        sa.Column("rmssd_floor_clean",       sa.Float(), nullable=True),
        sa.Column("rmssd_ceiling_clean",     sa.Float(), nullable=True),
        sa.Column("rmssd_morning_avg_clean", sa.Float(), nullable=True),
        # Filter stats
        sa.Column("windows_total",    sa.Integer(), nullable=True),
        sa.Column("windows_rejected", sa.Integer(), nullable=True),
        sa.Column("confidence",       sa.Float(),   nullable=True),
        # Outcome flags
        sa.Column("committed",     sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("sanity_passed", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.create_index(
        "ix_calibration_snapshots_user_day",
        "calibration_snapshots",
        ["user_id", "day_number"],
    )


def downgrade() -> None:
    op.drop_index("ix_calibration_snapshots_user_day", table_name="calibration_snapshots")
    op.drop_table("calibration_snapshots")
