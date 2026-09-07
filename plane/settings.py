"""Django settings for the KWIP data marketplace.

Reads configuration from environment variables for 12-factor compliance.
Docker Compose sets these via .env; Heroku sets them via config vars.
"""

import os
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get(
    "SECRET_KEY",
    "insecure-dev-key-change-in-production",
)

DEBUG = os.environ.get("DEBUG", "true").lower() == "true"

ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

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
    "pyscoped",
    "plane.core",
    "plane.billing",
    "plane.public",
    "plane.access",
    "plane.catalog",
    "plane.commerce",
    "plane.exports",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "plane.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
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
# Database
# ---------------------------------------------------------------------------

# Heroku sets DATABASE_URL automatically. Docker Compose sets it via .env.
# Fallback to individual POSTGRES_* vars for backwards compatibility.
DATABASES = {
    "default": dj_database_url.config(
        default="postgres://{user}:{password}@{host}:{port}/{name}".format(
            user=os.environ.get("POSTGRES_USER", "pyscoped"),
            password=os.environ.get("POSTGRES_PASSWORD", "pyscoped"),
            host=os.environ.get("POSTGRES_HOST", "localhost"),
            port=os.environ.get("POSTGRES_PORT", "5432"),
            name=os.environ.get("POSTGRES_DB", "pyscoped_plane"),
        ),
        conn_max_age=600,
    )
}

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# ---------------------------------------------------------------------------
# Security — production hardening (disabled when DEBUG=True)
# ---------------------------------------------------------------------------

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True

if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

# ---------------------------------------------------------------------------
# i18n
# ---------------------------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Marketplace configuration: explicit new boundaries; old service credentials are
# retained for recovery and never imply old customer entitlements.
MARKET_CLERK_ISSUER = os.environ.get("MARKET_CLERK_ISSUER", "")
MARKET_CLERK_PUBLIC_KEY = os.environ.get("MARKET_CLERK_PUBLIC_KEY", "")
MARKET_CLERK_PUBLISHABLE_KEY = os.environ.get("CLERK_PUBLISHABLE_KEY", "")
MARKET_AUTHORIZED_PARTIES = os.environ.get("MARKET_AUTHORIZED_PARTIES", "https://kwip.tech,https://www.kwip.tech").split(",")
MARKET_REQUESTS_PER_MINUTE = int(os.environ.get("MARKET_REQUESTS_PER_MINUTE", "120"))
MARKET_ORIGIN = os.environ.get("MARKET_ORIGIN", "https://kwip.tech")
DATA_UPLOAD_MAX_MEMORY_SIZE = 1048576

MARKET_TRUST_HEROKU_PROXY = os.environ.get("MARKET_TRUST_HEROKU_PROXY", "false").lower() == "true"

MARKET_BILLING_ENABLED = os.environ.get("MARKET_BILLING_ENABLED", "false").lower() == "true"
MARKET_STRIPE_SECRET_KEY = os.environ.get("MARKET_STRIPE_SECRET_KEY", "")
MARKET_STRIPE_WEBHOOK_SECRET = os.environ.get("MARKET_STRIPE_WEBHOOK_SECRET", "")
MARKET_STRIPE_PRO_PRICE_ID = os.environ.get("MARKET_STRIPE_PRO_PRICE_ID", "")
MARKET_STRIPE_OVERAGE_PRICE_ID = os.environ.get("MARKET_STRIPE_OVERAGE_PRICE_ID", "")
MARKET_STRIPE_PORTAL_CONFIGURATION_ID = os.environ.get("MARKET_STRIPE_PORTAL_CONFIGURATION_ID", "")
MARKET_STRIPE_METER_EVENT = os.environ.get("MARKET_STRIPE_METER_EVENT", "kwip_overage_credits")
MARKET_STRIPE_LIVEMODE = os.environ.get("MARKET_STRIPE_LIVEMODE", "false").lower() == "true"
MARKET_FREE_CREDITS = int(os.environ.get("MARKET_FREE_CREDITS", "1000"))
MARKET_PRO_CREDITS = int(os.environ.get("MARKET_PRO_CREDITS", "100000"))
MARKET_PRO_MONTHLY_CENTS = int(os.environ.get("MARKET_PRO_MONTHLY_CENTS", "2900"))
MARKET_OVERAGE_CENTS_PER_10000 = int(os.environ.get("MARKET_OVERAGE_CENTS_PER_10000", "100"))

MARKET_CLERK_WEBHOOK_SECRET = os.environ.get("MARKET_CLERK_WEBHOOK_SECRET", "")
MARKET_JWKS_REFRESH_SECONDS = 60
MARKET_JWKS_CACHE_SECONDS = 300
MARKET_JWKS_TIMEOUT_SECONDS = 5
