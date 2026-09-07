release: python manage.py migrate --noinput && python manage.py collectstatic --noinput
web: gunicorn plane.wsgi:application --bind 0.0.0.0:$PORT
worker: python manage.py run_marketplace_worker
