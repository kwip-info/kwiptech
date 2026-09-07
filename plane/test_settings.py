"""Tests use the production routes and installed apps with a local database."""
from plane.settings import *  # noqa: F401,F403
DEBUG = True
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
STORAGES = {"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0
