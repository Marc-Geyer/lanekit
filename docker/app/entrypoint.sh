#!/bin/sh
set -e

# ── Wait for PostgreSQL ───────────────────────────────────────────────────────
if [ -n "$DB_HOST" ]; then
  echo "[entrypoint] Waiting for PostgreSQL at $DB_HOST:${DB_PORT:-5432}…"
  until nc -z "$DB_HOST" "${DB_PORT:-5432}"; do
    sleep 0.5
  done
  echo "[entrypoint] PostgreSQL is ready."
fi

# ── Wait for Redis ────────────────────────────────────────────────────────────
if [ -n "$REDIS_URL" ]; then
  REDIS_HOST=$(echo "$REDIS_URL" | sed 's|redis://||' | cut -d: -f1)
  REDIS_PORT=$(echo "$REDIS_URL" | sed 's|redis://||' | cut -d: -f2 | cut -d/ -f1)
  echo "[entrypoint] Waiting for Redis at $REDIS_HOST:${REDIS_PORT:-6379}…"
  until nc -z "$REDIS_HOST" "${REDIS_PORT:-6379}"; do
    sleep 0.5
  done
  echo "[entrypoint] Redis is ready."
fi

# ── Migrations ────────────────────────────────────────────────────────────────
echo "[entrypoint] Running migrations…"
python manage.py migrate --noinput

# ── Superuser (first boot only, skipped if user already exists) ───────────────
if [ -n "$DJANGO_SUPERUSER_USERNAME" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
  echo "[entrypoint] Ensuring superuser '${DJANGO_SUPERUSER_USERNAME}' exists…"
  python manage.py createsuperuser --noinput 2>/dev/null && \
    echo "[entrypoint] Superuser created." || \
    echo "[entrypoint] Superuser already exists, skipping."
fi

# ── Static files (production only – skipped in dev where DEBUG=True) ──────────
if [ "$DEBUG" != "True" ]; then
  echo "[entrypoint] Collecting static files…"
  python manage.py collectstatic --noinput --clear
fi

echo "[entrypoint] Starting server…"
exec "$@"
