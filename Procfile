release: python manage.py migrate --noinput && python manage.py seed_plans && python manage.py collectstatic --noinput
web: python manage.py sync_pyscoped_docs --output /tmp/pyscoped-docs 2>/dev/null; gunicorn plane.wsgi:application --bind 0.0.0.0:$PORT
