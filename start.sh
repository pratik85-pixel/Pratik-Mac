#!/bin/sh
set -e

echo "=== ZenFlow Verity API ==="
echo "PORT=${PORT:-8000}"

echo "Running migrations (waiting 3s for DB)..."
sleep 3
alembic upgrade head

echo "Starting Uvicorn..."
exec uvicorn api.main:app --host 0.0.0.0 --port "${PORT:-8000}"
