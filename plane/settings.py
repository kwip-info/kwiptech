"""Django settings for pyscoped management plane.

Reads configuration from environment variables for 12-factor compliance.
Docker Compose sets these via .env or environment directives.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "insecure-dev-key-change-in-production",
)

DEBUG = os.environ.get("DJANGO_DEBUG", "true").lower() == "true"

ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

# ---------------------------------------------------------------------------
# Apps
# ---------------------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    # pyscoped dogfooding — the management plane eats its own dogfood.
    # Every operation on the platform is audited, isolated, and versioned
    # through the same framework we sell.
    "scoped.contrib.django",
    "plane.core",
    "plane.billing",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # pyscoped context injection — attributes every request to a principal
    "scoped.contrib.django.middleware.ScopedContextMiddleware",
]

ROOT_URLCONF = "plane.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "plane.wsgi.application"

# ---------------------------------------------------------------------------
# Database — Postgres via Docker Compose
# ---------------------------------------------------------------------------

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "pyscoped_plane"),
        "USER": os.environ.get("POSTGRES_USER", "pyscoped"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "pyscoped"),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

# ---------------------------------------------------------------------------
# DRF
# ---------------------------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "plane.api.auth.ApiKeyAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "EXCEPTION_HANDLER": "plane.api.exceptions.api_exception_handler",
}

# ---------------------------------------------------------------------------
# pyscoped — dogfooding configuration
# ---------------------------------------------------------------------------

# The management plane uses pyscoped's DjangoORMBackend, which creates
# pyscoped's schema tables alongside our own Django models in the same
# Postgres database. Every API request is attributed to a pyscoped
# principal via the ScopedContextMiddleware.

# Resolve the acting principal from the API key authentication.
# The middleware calls this function with the request; we return the
# pyscoped principal matching the authenticated account.
SCOPED_PRINCIPAL_RESOLVER = "plane.api.principal_resolver.resolve_principal"

# Exempt health check and provisioning from principal resolution.
SCOPED_EXEMPT_PATHS = ["/v1/ping", "/v1/provision"]

# ---------------------------------------------------------------------------
# Static / i18n
# ---------------------------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
