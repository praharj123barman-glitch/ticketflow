#!/usr/bin/env sh
# Render start script: migrate, seed demo data, then serve site + API on $PORT.
set -e

# Render sets RENDER_EXTERNAL_URL (e.g. https://ticketflow.onrender.com); use it
# for share links / OpenGraph tags unless PUBLIC_BASE_URL is set explicitly.
export PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-$RENDER_EXTERNAL_URL}"

echo "Running database migrations..."
alembic upgrade head

echo "Seeding demo data (idempotent)..."
python seed.py || echo "Seeding failed; continuing so the app still starts."

echo "Starting gunicorn on port ${PORT:-8000}..."
exec gunicorn -c gunicorn_conf.py --bind "0.0.0.0:${PORT:-8000}" app.render_app:app
