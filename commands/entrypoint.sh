#!/bin/bash
set -e

if [[ "$*" == *"uvicorn"* ]]; then
  echo "Detected app start, running migrations..."
  alembic upgrade head

  echo "Seeding initial data..."
  python app/manage.py seed_users
fi

echo "Starting command: $*"
exec "$@"