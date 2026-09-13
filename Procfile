release: python manage.py collectstatic --noinput --settings=show.settings
web: gunicorn show.wsgi:application --bind 0.0.0.0:$PORT
