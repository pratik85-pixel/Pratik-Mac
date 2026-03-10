"""add unified user profile and user facts tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-10 14:00:00.000000

Adds two tables:
  - user_unified_profiles: nightly-rebuilt personality skeleton (Layer 1 narrative + Layer 2 plan)
  - user_facts: durable structured facts extracted from conversations
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── user_unified_profiles ─────────────────────────────────────────────────
    op.create_table(
        "user_unified_profiles",
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
        sa.Column("narrative_version", sa.Integer, server_default="1"),
        # Narrative
        sa.Column("coach_narrative", sa.Text, nullable=True),
        sa.Column("previous_narrative", sa.Text, nullable=True),
        # Identity
        sa.Column("archetype_primary", sa.String(40), nullable=True),
        sa.Column("archetype_secondary", sa.String(40), nullable=True),
        sa.Column("training_level", sa.Integer, nullable=True),
        sa.Column("days_active", sa.Integer, server_default="0"),
        # Physiological
        sa.Column("prf_bpm", sa.Float, nullable=True),
        sa.Column("prf_status", sa.String(20), nullable=True),
        sa.Column("coherence_trainability", sa.String(20), nullable=True),
        sa.Column("recovery_arc_speed", sa.String(20), nullable=True),
        sa.Column("stress_peak_pattern", sa.String(80), nullable=True),
        sa.Column("sleep_recovery_efficiency", sa.Float, nullable=True),
        # Psychological
        sa.Column("social_energy_type", sa.String(20), nullable=True),
        sa.Column("anxiety_sensitivity", sa.Float, nullable=True),
        sa.Column("top_anxiety_triggers", sa.JSON, nullable=True),
        sa.Column("primary_recovery_style", sa.String(30), nullable=True),
        sa.Column("discipline_index", sa.Float, nullable=True),
        sa.Column("streak_current", sa.Integer, server_default="0"),
        sa.Column("mood_baseline", sa.String(20), nullable=True),
        sa.Column("interoception_alignment", sa.Float, nullable=True),
        # Behavioural
        sa.Column("top_calming_activities", sa.JSON, nullable=True),
        sa.Column("top_stress_activities", sa.JSON, nullable=True),
        sa.Column("habits_summary", sa.JSON, nullable=True),
        # Engagement
        sa.Column("band_days_worn_last7", sa.Integer, nullable=True),
        sa.Column("band_days_worn_last30", sa.Integer, nullable=True),
        sa.Column("morning_read_streak", sa.Integer, server_default="0"),
        sa.Column("morning_read_rate_30d", sa.Float, nullable=True),
        sa.Column("sessions_last7", sa.Integer, server_default="0"),
        sa.Column("sessions_last30", sa.Integer, server_default="0"),
        sa.Column("conversations_last7", sa.Integer, server_default="0"),
        sa.Column("nudge_response_rate_30d", sa.Float, nullable=True),
        sa.Column("last_app_interaction_days", sa.Integer, nullable=True),
        sa.Column("engagement_tier", sa.String(20), nullable=True),
        sa.Column("engagement_trend", sa.String(20), nullable=True),
        # Coach relationship
        sa.Column("preferred_tone", sa.String(20), nullable=True),
        sa.Column("nudge_response_rate", sa.Float, nullable=True),
        sa.Column("best_nudge_window", sa.String(5), nullable=True),
        sa.Column("last_insight_delivered", sa.Text, nullable=True),
        # Layer 2 plan
        sa.Column("suggested_plan_json", sa.JSON, nullable=True),
        sa.Column("plan_generated_for_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("plan_guardrail_notes", sa.JSON, nullable=True),
        # Metadata
        sa.Column("data_confidence", sa.Float, server_default="0.0"),
        sa.Column("last_computed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── user_facts ────────────────────────────────────────────────────────────
    op.create_table(
        "user_facts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column("last_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("fact_text", sa.String(200), nullable=False),
        sa.Column("fact_key", sa.String(60), nullable=True),
        sa.Column("fact_value", sa.String(200), nullable=True),
        sa.Column("polarity", sa.String(10), server_default="neutral"),
        sa.Column("confidence", sa.Float, server_default="0.5"),
        sa.Column("source_conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_confirmed", sa.Boolean, server_default="false"),
    )

    op.create_index("ix_user_facts_user", "user_facts", ["user_id"])
    op.create_index("ix_user_facts_user_category", "user_facts", ["user_id", "category"])


def downgrade() -> None:
    op.drop_index("ix_user_facts_user_category", "user_facts")
    op.drop_index("ix_user_facts_user", "user_facts")
    op.drop_table("user_facts")
    op.drop_table("user_unified_profiles")
