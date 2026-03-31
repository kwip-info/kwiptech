"""WSGI config for pyscoped management plane."""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "plane.settings")

application = get_wsgi_application()
