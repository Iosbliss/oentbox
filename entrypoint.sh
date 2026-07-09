#!/bin/bash
set -e

echo "==> Running database migrations..."
python manage.py migrate --noinput

if [ "$SEED_DATABASE" = "true" ]; then
    echo "==> Seeding database..."
    python manage.py seed_movies
fi

exec "$@"