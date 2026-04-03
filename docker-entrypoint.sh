#!/bin/sh

set -e

echo "Waiting for database..."
until python -c "
import psycopg
conn = psycopg.connect('$DATABASE_URL')
conn.close()
" 2>/dev/null; do
    sleep 1
done
echo "Database is ready"

echo "Running database migrations..."
python manage.py migrate --noinput

echo "Seeding plans..."
python manage.py seed_plans

echo "Syncing SDK docs..."
python manage.py sync_pyscoped_docs --output /app/pyscoped-docs 2>/dev/null || true

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Starting Django development server..."
python manage.py runserver 0.0.0.0:8000
