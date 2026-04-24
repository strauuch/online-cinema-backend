#!/bin/bash
set -e

echo "Running migrations..."
alembic upgrade head

echo "Seeding initial data..."
python app/manage.py seed_users

echo "Starting FastAPI..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000