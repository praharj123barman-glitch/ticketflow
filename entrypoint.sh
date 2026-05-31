#!/usr/bin/env sh
# Container entrypoint: apply DB migrations, then start the app server.
# Running migrations here (not in app startup) keeps schema changes explicit and
# idempotent — `alembic upgrade head` is a no-op when already current.
set -e

echo "Running database migrations..."
alembic upgrade head

echo "Starting gunicorn..."
exec gunicorn -c gunicorn_conf.py app.main:app
