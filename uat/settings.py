"""Isolated synthetic browser UAT. Never use this settings module in production."""
import os
from django.core.exceptions import ImproperlyConfigured
if os.environ.get('KWIP_UAT') != '1':
    raise ImproperlyConfigured('Synthetic UAT requires KWIP_UAT=1 and loopback-only runserver.')
from plane.settings import *  # noqa: F401,F403,E402
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

DEBUG = True
SECRET_KEY = 'synthetic-uat-not-a-production-secret'
ALLOWED_HOSTS = ['localhost', '127.0.0.1', 'testserver']
# Deliberately fixed loopback-only fixture database; never accepts DATABASE_URL.
DATABASES = {'default': {'ENGINE': 'django.db.backends.postgresql', 'NAME': 'market_uat', 'USER': 'postgres', 'PASSWORD': 'catalog-local-only', 'HOST': '127.0.0.1', 'PORT': '55439'}}
ROOT_URLCONF = 'uat.urls'
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
STORAGES = {'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}}
MARKET_CLERK_ISSUER = 'http://127.0.0.1:8043'
MARKET_ORIGIN = 'http://127.0.0.1:8043'
MARKET_AUTHORIZED_PARTIES = ['http://127.0.0.1:8043']
MARKET_CLERK_PUBLISHABLE_KEY = 'pk_test_synthetic_uat_only'
UAT_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
MARKET_CLERK_PUBLIC_KEY = UAT_PRIVATE_KEY.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
MARKET_BILLING_ENABLED = False
MARKET_STRIPE_SECRET_KEY = ''
MARKET_STRIPE_WEBHOOK_SECRET = ''
MARKET_REQUESTS_PER_MINUTE = 500

# Allow only same-origin embedding for the synthetic390px responsive harness.
X_FRAME_OPTIONS = 'SAMEORIGIN'
