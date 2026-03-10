#!/usr/bin/env bash
# scripts/dev_setup.sh
#
# One-shot dev environment setup for ZenFlow Verity.
# Run this after cloning or before band testing.
#
# Usage:
#   ./scripts/dev_setup.sh              # full setup
#   ./scripts/dev_setup.sh --migrate    # migrations only (DB already exists)
#   ./scripts/dev_setup.sh --seed       # seed only (tables already migrated)
#
# Prerequisites:
#   - PostgreSQL running locally (brew services start postgresql@16)
#   - .env file present (cp .env.example .env and edit if needed)
#   - .venv present (.venv/bin/python must exist)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

PYTHON=".venv/bin/python"
ALEMBIC=".venv/bin/alembic"

# ── Parse flags ───────────────────────────────────────────────────────────────
MIGRATE_ONLY=false
SEED_ONLY=false
for arg in "$@"; do
  case $arg in
    --migrate) MIGRATE_ONLY=true ;;
    --seed)    SEED_ONLY=true ;;
  esac
done

# ── Checks ────────────────────────────────────────────────────────────────────
if [[ ! -f ".env" ]]; then
  echo "⚠️  No .env found — copying from .env.example"
  cp .env.example .env
  echo "   Edit .env if needed, then re-run this script."
fi

if [[ ! -x "$PYTHON" ]]; then
  echo "❌  .venv/bin/python not found. Run: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

if [[ ! -x "$ALEMBIC" ]]; then
  echo "❌  .venv/bin/alembic not found. Run: .venv/bin/pip install -r requirements.txt"
  exit 1
fi

# ── Load DATABASE_SYNC_URL from .env ─────────────────────────────────────────
DB_SYNC_URL=$(grep -E "^DATABASE_SYNC_URL" .env | cut -d= -f2- | tr -d '"' | tr -d "'")
DB_SYNC_URL="${DB_SYNC_URL:-postgresql+psycopg2://zenflow:zenflow@localhost:5432/zenflow_dev}"

# Extract host, port, user, password, dbname for psql
# Format: postgresql+psycopg2://user:pass@host:port/dbname
DB_USER=$(echo "$DB_SYNC_URL" | sed -E 's|.*://([^:]+):.*|\1|')
DB_PASS=$(echo "$DB_SYNC_URL" | sed -E 's|.*://[^:]+:([^@]+)@.*|\1|')
DB_HOST=$(echo "$DB_SYNC_URL" | sed -E 's|.*@([^:/]+).*|\1|')
DB_PORT=$(echo "$DB_SYNC_URL" | sed -E 's|.*:([0-9]+)/.*|\1|')
DB_NAME=$(echo "$DB_SYNC_URL" | sed -E 's|.*/([^?]+).*|\1|')

# ── Step 1: Create DB if it doesn't exist ────────────────────────────────────
if [[ "$SEED_ONLY" == "false" ]]; then
  echo ""
  echo "▶  Checking database: $DB_NAME on $DB_HOST:$DB_PORT"

  DB_EXISTS=$(PGPASSWORD="$DB_PASS" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" \
    -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" postgres 2>/dev/null || echo "")

  if [[ "$DB_EXISTS" != "1" ]]; then
    echo "   Creating database $DB_NAME..."
    PGPASSWORD="$DB_PASS" createdb -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME"
    echo "   ✅ Database created."
  else
    echo "   ✅ Database already exists."
  fi
fi

# ── Step 2: Run Alembic migrations ───────────────────────────────────────────
if [[ "$SEED_ONLY" == "false" ]]; then
  echo ""
  echo "▶  Running Alembic migrations (upgrade head)..."
  $ALEMBIC upgrade head
  echo "   ✅ Migrations applied."
fi

# ── Step 3: Seed dev data ─────────────────────────────────────────────────────
if [[ "$MIGRATE_ONLY" == "false" ]]; then
  echo ""
  echo "▶  Seeding dev data..."
  $PYTHON -m api.db.seed
  echo "   ✅ Seed complete."
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅  ZenFlow Verity dev environment ready."
echo ""
echo "   Dev user ID : 00000000-0000-0000-0000-000000000001"
echo "   X-User-Id header: 00000000-0000-0000-0000-000000000001"
echo ""
echo "   Start the server:"
echo "     .venv/bin/uvicorn api.main:app --reload --port 8000"
echo ""
echo "   WebSocket stream endpoint:"
echo "     ws://localhost:8000/ws/stream"
echo ""
echo "   API docs:"
echo "     http://localhost:8000/docs"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
