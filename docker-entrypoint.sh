#!/bin/sh
set -e
python manage.py collectstatic --noinput --settings=show.settings
exec python manage.py runserver 0.0.0.0:8000 --settings=show.settings
