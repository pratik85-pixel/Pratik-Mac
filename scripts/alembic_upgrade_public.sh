#!/usr/bin/env bash
# Run Alembic against Railway Postgres using the PUBLIC connection string (works
# from your laptop; internal postgres.railway.internal does not resolve locally).
#
# Railway → Postgres → Variables: copy DATABASE_PUBLIC_URL (or public URL from Connect).
#
#   export DATABASE_PUBLIC_URL='postgresql://...'
#   ./scripts/alembic_upgrade_public.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
RAW="${DATABASE_PUBLIC_URL:-}"
if [[ -z "$RAW" ]]; then
  echo "Set DATABASE_PUBLIC_URL to your Railway Postgres public URL, then re-run." >&2
  exit 1
fi
# Alembic sync driver
if [[ "$RAW" == postgresql://* ]]; then
  export DATABASE_SYNC_URL="postgresql+psycopg2://${RAW#postgresql://}"
elif [[ "$RAW" == postgres://* ]]; then
  export DATABASE_SYNC_URL="postgresql+psycopg2://${RAW#postgres://}"
else
  export DATABASE_SYNC_URL="$RAW"
fi
echo "Running: alembic upgrade head"
alembic upgrade head
echo "Current revision:"
alembic current
