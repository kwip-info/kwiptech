release: python manage.py collectstatic --noinput && python manage.py migrate --noinput
web: gunicorn plane.wsgi:application --bind 0.0.0.0:$PORT
