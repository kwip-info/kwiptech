"""Django settings for pyscoped management plane.

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
    "rest_framework",
    # pyscoped dogfooding — the management plane eats its own dogfood.
    # Every operation on the platform is audited, isolated, and versioned
    # through the same framework we sell.
    "scoped.contrib.django",
    "plane.core",
    "plane.billing",
    "plane.dashboard",
    "plane.public",
    "plane.webhooks",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "plane.auth.middleware.ClerkAuthMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # pyscoped context injection — attributes every request to a principal
    "scoped.contrib.django.middleware.ScopedContextMiddleware",
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
                "plane.dashboard.context_processors.clerk_settings",
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
# Clerk — frontend authentication for dashboard
# ---------------------------------------------------------------------------

CLERK_PUBLISHABLE_KEY = os.environ.get("CLERK_PUBLISHABLE_KEY", "")
CLERK_SECRET_KEY = os.environ.get("CLERK_SECRET_KEY", "")
CLERK_JWKS_URL = os.environ.get("CLERK_JWKS_URL", "")
CLERK_JWKS_CACHE_TTL = int(os.environ.get("CLERK_JWKS_CACHE_TTL", "3600"))
CLERK_WEBHOOK_SECRET = os.environ.get("CLERK_WEBHOOK_SECRET", "")

# Stripe
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_PUBLIC_KEY = os.environ.get("STRIPE_PUBLIC_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

# Validate Stripe config in production
if not DEBUG and STRIPE_SECRET_KEY:
    if not STRIPE_SECRET_KEY.startswith(("sk_live_", "sk_test_")):
        raise ValueError("STRIPE_SECRET_KEY must start with sk_live_ or sk_test_")
    if not STRIPE_WEBHOOK_SECRET.startswith("whsec_"):
        raise ValueError("STRIPE_WEBHOOK_SECRET must start with whsec_")
elif not DEBUG and not STRIPE_SECRET_KEY:
    import warnings
    warnings.warn(
        "STRIPE_SECRET_KEY not set — billing is disabled. "
        "Set it to enable paid plans and usage metering.",
        RuntimeWarning,
        stacklevel=1,
    )

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
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "20/minute",
        "user": "120/minute",
        "sync": "30/minute",
        "key_create": "10/minute",
    },
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
SCOPED_EXEMPT_PATHS = [
    "/v1/ping", "/v1/provision", "/admin/",
    "/pricing", "/status", "/security",
    "/terms", "/privacy", "/cookies", "/docs",
    "/sign-in", "/sign-up", "/static/",
    "/webhooks/",
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
# Email
# ---------------------------------------------------------------------------

EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend"
)
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "noreply@kwip.info")

# ---------------------------------------------------------------------------
# i18n
# ---------------------------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
