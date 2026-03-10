"""add psychological profile tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-10 12:00:00.000000

Adds three tables:
  - user_psych_profiles: inferred behavioural/psychological fingerprint
  - mood_logs: daily subjective state (mood, energy, anxiety, social desire)
  - anxiety_events: structured anxiety trigger records
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── user_psych_profiles ───────────────────────────────────────────────────
    op.create_table(
        "user_psych_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            unique=True,
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # Social energy
        sa.Column("social_energy_type", sa.String(20), nullable=True),
        sa.Column("social_hrv_delta_avg", sa.Float, nullable=True),
        sa.Column("social_event_count", sa.Integer, nullable=True, server_default="0"),
        # Anxiety sensitivity
        sa.Column("anxiety_sensitivity", sa.Float, nullable=True),
        sa.Column("top_anxiety_triggers", sa.JSON, nullable=True),
        # Activity ↔ physiology map
        sa.Column("top_calming_activities", sa.JSON, nullable=True),
        sa.Column("top_stress_activities", sa.JSON, nullable=True),
        # Recovery style
        sa.Column("primary_recovery_style", sa.String(30), nullable=True),
        # Discipline
        sa.Column("discipline_index", sa.Float, nullable=True),
        sa.Column("streak_current", sa.Integer, nullable=True, server_default="0"),
        sa.Column("streak_best", sa.Integer, nullable=True, server_default="0"),
        # Mood baseline
        sa.Column("mood_baseline", sa.String(20), nullable=True),
        sa.Column("mood_score_avg", sa.Float, nullable=True),
        # Interoception alignment
        sa.Column("interoception_alignment", sa.Float, nullable=True),
        # Metadata
        sa.Column("data_confidence", sa.Float, nullable=True, server_default="0.0"),
        sa.Column("last_computed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── mood_logs ─────────────────────────────────────────────────────────────
    op.create_table(
        "mood_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("log_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("mood_score", sa.Integer, nullable=False),
        sa.Column("energy_score", sa.Integer, nullable=True),
        sa.Column("anxiety_score", sa.Integer, nullable=True),
        sa.Column("social_desire", sa.Integer, nullable=True),
        sa.Column("readiness_score_at_log", sa.Float, nullable=True),
        sa.Column("stress_score_at_log", sa.Float, nullable=True),
        sa.Column("recovery_score_at_log", sa.Float, nullable=True),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
    )
    op.create_index("ix_mood_logs_user_date", "mood_logs", ["user_id", "log_date"])

    # ── anxiety_events ────────────────────────────────────────────────────────
    op.create_table(
        "anxiety_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("trigger_type", sa.String(40), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column(
            "stress_window_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("stress_windows.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("stress_score_at_event", sa.Float, nullable=True),
        sa.Column("recovery_score_drop", sa.Float, nullable=True),
        sa.Column("resolution_activity", sa.String(50), nullable=True),
        sa.Column("resolved", sa.Boolean, nullable=True),
        sa.Column("reported_via", sa.String(30), nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
    )
    op.create_index("ix_anxiety_events_user_ts", "anxiety_events", ["user_id", "ts"])


def downgrade() -> None:
    op.drop_table("anxiety_events")
    op.drop_table("mood_logs")
    op.drop_table("user_psych_profiles")
