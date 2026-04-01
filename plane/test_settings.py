"""Test settings — SQLite backend, no external dependencies required."""

from plane.settings import *  # noqa: F401, F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# Disable scoped contrib during tests — it tries to connect at startup
INSTALLED_APPS = [  # noqa: F811
    app for app in INSTALLED_APPS if app != "scoped.contrib.django"
]

MIDDLEWARE = [  # noqa: F811
    mw for mw in MIDDLEWARE
    if mw not in (
        "scoped.contrib.django.middleware.ScopedContextMiddleware",
        "plane.auth.middleware.ClerkAuthMiddleware",
    )
]

# Clerk settings disabled for tests
CLERK_PUBLISHABLE_KEY = ""
CLERK_SECRET_KEY = ""
CLERK_JWKS_URL = ""

# Use a test middleware that sets clerk_user for dashboard view tests
MIDDLEWARE.append("plane.dashboard.tests.test_middleware_helper.TestClerkMiddleware")  # noqa: F405

# Use basic static files storage (no manifest required)
STORAGES = {
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

# Use test URL config that excludes v1 API (requires scoped package)
ROOT_URLCONF = "plane.test_urls"
