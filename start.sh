#!/bin/sh
echo "=== ZenFlow Verity API ==="
echo "Running migrations..."
alembic upgrade head && echo "Migrations OK" || echo "WARNING: migrations failed"
echo "Starting Uvicorn on port ${PORT:-8000}..."
exec uvicorn api.main:app --host 0.0.0.0 --port "${PORT:-8000}"
