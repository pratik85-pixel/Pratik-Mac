#!/bin/sh
set -e

echo "=== ZenFlow Verity API starting ==="
echo "PORT=${PORT:-8000}"

echo "--- Checking Python imports ---"
python -c "from api.config import get_settings; s=get_settings(); print('DB URL ok:', s.DATABASE_URL[:35])"

echo "--- Running migrations ---"
for i in 1 2 3 4 5; do
    alembic upgrade head && break
    echo "Migration attempt $i failed, retrying in 5s..."
    sleep 5
done

echo "--- Starting Uvicorn ---"
exec uvicorn api.main:app --host 0.0.0.0 --port "${PORT:-8000}"
