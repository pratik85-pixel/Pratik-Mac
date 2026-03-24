"""phase3: add morning_brief, coach_watch_notes, avoid_items to user_unified_profiles

Revision ID: k6l7m8n9o0p1
Revises: j5k6l7m8n9o0
Create Date: 2026-03-24

Adds columns that support:
  1. Morning brief (generated at wake-up, displayed on Home Screen)
  2. Coach watch notes (hyper-personalised insight bullets from Layer 1)
  3. Avoid items (Layer 2 don'ts alongside the do's plan)
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision      = 'k6l7m8n9o0p1'
down_revision = 'j5k6l7m8n9o0'
branch_labels = None
depends_on    = None


def upgrade() -> None:
    # ── Coach Watch Notes (Layer 1 nightly) ────────────────────────────────────
    # 3–5 hyper-personal insight bullets written by Layer 1 LLM.
    # JSON: list[str]
    op.add_column(
        'user_unified_profiles',
        sa.Column('coach_watch_notes', sa.JSON(), nullable=True),
    )

    # ── Avoid Items (Layer 2 nightly) ─────────────────────────────────────────
    # Things the user should avoid today — companion to suggested_plan_json.
    # JSON: [{"slug_or_label": str, "reason": str}]
    op.add_column(
        'user_unified_profiles',
        sa.Column('avoid_items_json', sa.JSON(), nullable=True),
    )

    # ── Morning Brief fields (generated at wake-up / sleep→background) ────────
    op.add_column(
        'user_unified_profiles',
        sa.Column('morning_brief_text', sa.Text(), nullable=True),
    )
    op.add_column(
        'user_unified_profiles',
        sa.Column('morning_brief_day_state', sa.String(10), nullable=True),
    )
    op.add_column(
        'user_unified_profiles',
        sa.Column('morning_brief_day_confidence', sa.String(10), nullable=True),
    )
    op.add_column(
        'user_unified_profiles',
        sa.Column('morning_brief_evidence', sa.Text(), nullable=True),
    )
    op.add_column(
        'user_unified_profiles',
        sa.Column('morning_brief_one_action', sa.Text(), nullable=True),
    )
    # Date (no tz) — the IST calendar date this brief covers
    op.add_column(
        'user_unified_profiles',
        sa.Column('morning_brief_generated_for', sa.Date(), nullable=True),
    )
    op.add_column(
        'user_unified_profiles',
        sa.Column('morning_brief_generated_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('user_unified_profiles', 'morning_brief_generated_at')
    op.drop_column('user_unified_profiles', 'morning_brief_generated_for')
    op.drop_column('user_unified_profiles', 'morning_brief_one_action')
    op.drop_column('user_unified_profiles', 'morning_brief_evidence')
    op.drop_column('user_unified_profiles', 'morning_brief_day_confidence')
    op.drop_column('user_unified_profiles', 'morning_brief_day_state')
    op.drop_column('user_unified_profiles', 'morning_brief_text')
    op.drop_column('user_unified_profiles', 'avoid_items_json')
    op.drop_column('user_unified_profiles', 'coach_watch_notes')
