release: python manage.py collectstatic --noinput && python manage.py migrate --noinput && python manage.py seed_plans && python manage.py sync_pyscoped_docs
web: gunicorn plane.wsgi:application --bind 0.0.0.0:$PORT
