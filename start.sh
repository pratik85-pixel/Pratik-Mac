#!/bin/sh

echo "=== ZenFlow Verity API ==="
echo "PORT=${PORT:-8000}"

echo "Running migrations (non-fatal)..."
alembic upgrade head || echo "WARNING: migrations failed - tables may be missing"

echo "Starting Uvicorn..."
exec uvicorn api.main:app --host 0.0.0.0 --port "${PORT:-8000}"
