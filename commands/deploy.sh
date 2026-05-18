#!/bin/bash
set -e

cd ~/src/online-cinema-backend

git pull origin main

docker compose build --no-cache app celery_worker celery_beat
docker compose up -d --remove-orphans
docker compose exec -T app poetry run alembic upgrade head
docker image prune -f