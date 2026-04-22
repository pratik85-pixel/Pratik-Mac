"""composite indexes on hot tables (sessions, coach_messages, conversation_events, check_ins, model_snapshots, tags, band_wear_sessions)

Revision ID: w2x3y4z5a6b7
Revises: 38b1eccbdf47
Create Date: 2026-04-22

Adds `(user_id, <time>)` composite indexes to the foreign-key columns that
dominate read-path predicates. Postgres does not auto-index FKs, so these
queries were falling back to sequential scans for users with a lot of rows.

All indexes use `IF NOT EXISTS` so the migration is idempotent on DBs that
already have hand-rolled copies of the same index (important for ops safety).
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "w2x3y4z5a6b7"
down_revision = "38b1eccbdf47"
branch_labels = None
depends_on = None


_INDEX_STATEMENTS: list[tuple[str, str]] = [
    (
        "ix_sessions_user_started",
        "CREATE INDEX IF NOT EXISTS ix_sessions_user_started "
        "ON sessions (user_id, started_at DESC)",
    ),
    (
        "ix_sessions_user_context_started",
        "CREATE INDEX IF NOT EXISTS ix_sessions_user_context_started "
        "ON sessions (user_id, context, started_at DESC)",
    ),
    (
        "ix_coach_messages_user_type_created",
        "CREATE INDEX IF NOT EXISTS ix_coach_messages_user_type_created "
        "ON coach_messages (user_id, message_type, created_at DESC)",
    ),
    (
        "ix_conversation_events_user_ts",
        "CREATE INDEX IF NOT EXISTS ix_conversation_events_user_ts "
        "ON conversation_events (user_id, ts DESC)",
    ),
    (
        "ix_check_ins_user_ts",
        "CREATE INDEX IF NOT EXISTS ix_check_ins_user_ts "
        "ON check_ins (user_id, ts DESC)",
    ),
    (
        "ix_model_snapshots_user_created",
        "CREATE INDEX IF NOT EXISTS ix_model_snapshots_user_created "
        "ON model_snapshots (user_id, created_at DESC)",
    ),
    (
        "ix_tags_user_start",
        "CREATE INDEX IF NOT EXISTS ix_tags_user_start "
        "ON tags (user_id, start_time DESC)",
    ),
    (
        "ix_tags_stress_window",
        "CREATE INDEX IF NOT EXISTS ix_tags_stress_window "
        "ON tags (stress_window_id)",
    ),
    (
        "ix_tags_recovery_window",
        "CREATE INDEX IF NOT EXISTS ix_tags_recovery_window "
        "ON tags (recovery_window_id)",
    ),
    (
        "ix_band_wear_sessions_user_started",
        "CREATE INDEX IF NOT EXISTS ix_band_wear_sessions_user_started "
        "ON band_wear_sessions (user_id, started_at DESC)",
    ),
    (
        "ix_band_wear_sessions_user_closed_started",
        "CREATE INDEX IF NOT EXISTS ix_band_wear_sessions_user_closed_started "
        "ON band_wear_sessions (user_id, is_closed, started_at DESC)",
    ),
    (
        "ix_habit_events_user_ts",
        "CREATE INDEX IF NOT EXISTS ix_habit_events_user_ts "
        "ON habit_events (user_id, ts DESC)",
    ),
    (
        "ix_user_facts_user_category",
        "CREATE INDEX IF NOT EXISTS ix_user_facts_user_category "
        "ON user_facts (user_id, category)",
    ),
]


def upgrade() -> None:
    # Each CREATE INDEX runs in its own transaction (the default for Alembic
    # online migrations). Idempotent IF NOT EXISTS ensures a retry is safe.
    for _name, sql in _INDEX_STATEMENTS:
        op.execute(sql)


def downgrade() -> None:
    for name, _sql in reversed(_INDEX_STATEMENTS):
        op.execute(f"DROP INDEX IF EXISTS {name}")
