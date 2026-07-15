---
title: Deployment Guide
description: Complete guide for deploying the pyscoped platform, covering local development with Docker Compose, production deployment on Heroku, environment configuration, and security hardening.
category: Platform Operations
---

# Deployment Guide

This guide covers deploying the pyscoped platform from local development through production.

---

## Prerequisites

| Dependency     | Minimum Version | Notes                                      |
|----------------|-----------------|---------------------------------------------|
| Python         | 3.13+           | Required for modern type hints and stdlib.  |
| PostgreSQL     | 16+             | Primary datastore.                          |
| Clerk account  | --              | Authentication provider for the dashboard.  |
| Stripe account | --              | Billing and subscription management.        |

---

## Environment Variables

All configuration is driven by environment variables. Group them by category when setting up `.env` or config vars.

### Django Core

| Variable               | Required | Default                | Description                                                    |
|------------------------|----------|------------------------|----------------------------------------------------------------|
| `DJANGO_SECRET_KEY`    | Yes      | --                     | Secret key for cryptographic signing. Generate with `django.core.management.utils.get_random_secret_key()`. |
| `DJANGO_DEBUG`         | No       | `False`                | Set to `True` only in development. Never enable in production. |
| `DJANGO_ALLOWED_HOSTS` | Yes      | --                     | Comma-separated list of allowed hostnames (e.g. `kwip.tech,www.kwip.tech`). |
| `DJANGO_LOG_LEVEL`     | No       | `INFO`                 | Root logger level. Use `DEBUG` for development troubleshooting.|

### Database

| Variable       | Required | Default                           | Description                                                          |
|----------------|----------|-----------------------------------|----------------------------------------------------------------------|
| `DATABASE_URL` | Yes      | `postgres://localhost:5432/pyscoped` | PostgreSQL connection URL. On Heroku this is auto-provisioned.      |

The platform uses `dj-database-url` to parse `DATABASE_URL` into Django's `DATABASES` setting. Connection pooling parameters (`CONN_MAX_AGE`, `CONN_HEALTH_CHECKS`) are configured automatically.

### Clerk Authentication

| Variable                     | Required | Default | Description                                                |
|------------------------------|----------|---------|------------------------------------------------------------|
| `CLERK_SECRET_KEY`           | Yes      | --      | Clerk backend API secret key (`sk_live_...` or `sk_test_...`). |
| `CLERK_PUBLISHABLE_KEY`     | Yes      | --      | Clerk frontend publishable key (`pk_live_...` or `pk_test_...`). |
| `CLERK_WEBHOOK_SIGNING_SECRET` | Yes   | --      | Secret for verifying Clerk webhook payloads (Svix).        |
| `CLERK_SIGN_IN_URL`         | No       | `/sign-in` | Path to the Clerk sign-in page.                         |
| `CLERK_SIGN_UP_URL`         | No       | `/sign-up` | Path to the Clerk sign-up page.                         |
| `CLERK_AFTER_SIGN_IN_URL`   | No       | `/dashboard` | Redirect destination after successful sign-in.         |

### Stripe Billing

| Variable                       | Required | Default | Description                                                |
|--------------------------------|----------|---------|------------------------------------------------------------|
| `STRIPE_SECRET_KEY`            | Yes      | --      | Stripe API secret key (`sk_live_...` or `sk_test_...`).    |
| `STRIPE_PUBLISHABLE_KEY`      | Yes      | --      | Stripe publishable key for checkout sessions.              |
| `STRIPE_WEBHOOK_SECRET`       | Yes      | --      | Webhook endpoint signing secret (`whsec_...`).             |
| `STRIPE_STARTER_PRICE_ID`     | Yes      | --      | Stripe Price ID for the Starter plan.                      |
| `STRIPE_TEAM_PRICE_ID`        | Yes      | --      | Stripe Price ID for the Team plan.                         |
| `STRIPE_ENTERPRISE_PRICE_ID`  | Yes      | --      | Stripe Price ID for the Enterprise plan.                   |

### pyscoped Library

| Variable            | Required | Default       | Description                                              |
|---------------------|----------|---------------|----------------------------------------------------------|
| `PYSCOPED_DOCS_PATH`| No      | --            | Filesystem path to pyscoped library docs for sync. If not set, `sync_pyscoped_docs` pulls from the installed package. |

---

## Local Development with Docker Compose

The repository includes a `docker-compose.yml` for local development.

```bash
docker compose up -d
```

### Services

| Service      | Port  | Description                                  |
|--------------|-------|----------------------------------------------|
| `web`        | 8000  | Django development server with hot reload.   |
| `db`         | 5432  | PostgreSQL 16 with persistent volume.        |

### Volumes

- `postgres_data`: Persists database data across container restarts.

### Health Checks

The `db` service includes a health check that runs `pg_isready` every 5 seconds. The `web` service depends on `db` being healthy before starting:

```yaml
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_DB: pyscoped
      POSTGRES_USER: pyscoped
      POSTGRES_PASSWORD: pyscoped
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U pyscoped"]
      interval: 5s
      timeout: 5s
      retries: 5

  web:
    build: .
    command: python manage.py runserver 0.0.0.0:8000
    ports:
      - "8000:8000"
    env_file: .env
    depends_on:
      db:
        condition: service_healthy
    volumes:
      - .:/app

volumes:
  postgres_data:
```

After the containers start, run initial setup:

```bash
docker compose exec web python manage.py migrate
docker compose exec web python manage.py sync_pyscoped_docs
docker compose exec web python manage.py createsuperuser
```

---

## Heroku Deployment

### Procfile

```
release: python manage.py migrate && python manage.py sync_pyscoped_docs
web: gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 3
```

The `release` phase runs database migrations and syncs pyscoped library documentation on every deploy. This ensures the schema and embedded docs are always current.

### Buildpack

Use the official Python buildpack:

```bash
heroku buildpacks:set heroku/python
```

### Database

Provision Heroku Postgres. The `DATABASE_URL` environment variable is set automatically:

```bash
heroku addons:create heroku-postgresql:essential-0
```

### Config Vars

Set all required environment variables via the Heroku CLI or dashboard:

```bash
heroku config:set DJANGO_SECRET_KEY="$(python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())')"
heroku config:set DJANGO_ALLOWED_HOSTS="your-app.herokuapp.com,kwip.tech"
heroku config:set CLERK_SECRET_KEY="sk_live_..."
heroku config:set CLERK_PUBLISHABLE_KEY="pk_live_..."
heroku config:set CLERK_WEBHOOK_SIGNING_SECRET="whsec_..."
heroku config:set STRIPE_SECRET_KEY="sk_live_..."
heroku config:set STRIPE_PUBLISHABLE_KEY="pk_live_..."
heroku config:set STRIPE_WEBHOOK_SECRET="whsec_..."
heroku config:set STRIPE_STARTER_PRICE_ID="price_..."
heroku config:set STRIPE_TEAM_PRICE_ID="price_..."
heroku config:set STRIPE_ENTERPRISE_PRICE_ID="price_..."
```

### Deploy

```bash
git push heroku main
```

---

## Database Setup

Run migrations to create or update the schema:

```bash
python manage.py migrate
```

Migrations are idempotent and safe to run repeatedly. The release phase in the Procfile handles this automatically on Heroku.

### Seeded Data

The `Permission` model is populated via a data migration. Permissions are static and defined in code. No manual seeding is required.

---

## Static Files

Static files are served by [WhiteNoise](http://whitenoise.evans.io/) in production, eliminating the need for a separate static file server or CDN for most deployments.

Collect static files before serving:

```bash
python manage.py collectstatic --noinput
```

On Heroku this runs automatically during the build phase via the Python buildpack's post-compile hook.

WhiteNoise is configured in `settings.py`:

```python
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
```

This enables Brotli/gzip compression and cache-busting via content hashes in filenames.

---

## Security Settings (Production)

When `DJANGO_DEBUG` is `False`, the following security settings are enforced:

```python
# HTTPS enforcement
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# HSTS (HTTP Strict Transport Security)
SECURE_HSTS_SECONDS = 31536000        # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Cookie security
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True

# Content security
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
```

---

## Middleware Stack

Middleware is applied in order on every request. The sequence matters:

| Order | Middleware                                      | Purpose                                                       |
|-------|-------------------------------------------------|---------------------------------------------------------------|
| 1     | `SecurityMiddleware`                            | SSL redirect, HSTS headers, content type nosniff.             |
| 2     | `WhiteNoiseMiddleware`                          | Serves static files directly with compression and caching.    |
| 3     | `SessionMiddleware`                             | Manages server-side sessions.                                 |
| 4     | `CommonMiddleware`                              | URL normalization (trailing slashes, APPEND_SLASH).           |
| 5     | `CsrfViewMiddleware`                            | CSRF token validation for form submissions.                   |
| 6     | `AuthenticationMiddleware`                      | Attaches `request.user` from the session.                     |
| 7     | `ClerkAuthMiddleware`                           | Verifies Clerk JWTs, syncs Clerk user to Django `Account`.    |
| 8     | `MessageMiddleware`                             | Django messages framework (flash messages).                   |
| 9     | `XFrameOptionsMiddleware`                       | Sets `X-Frame-Options` header to prevent clickjacking.        |
| 10    | `ScopedContextMiddleware`                       | Resolves the pyscoped principal and attaches `ScopedContext` to the request. |

The `ClerkAuthMiddleware` runs after Django's built-in `AuthenticationMiddleware` so that `request.user` is already populated from the session. It then enriches the request with Clerk-specific data (organization context, membership info).

The `ScopedContextMiddleware` runs last because it depends on a resolved user and organization to construct the pyscoped `ScopedContext` for access control checks.

---

## Docs Sync

The `sync_pyscoped_docs` management command imports documentation from the pyscoped library into the platform's database for rendering in the dashboard.

```bash
python manage.py sync_pyscoped_docs
```

### Behavior

1. Reads Markdown files from `PYSCOPED_DOCS_PATH` (or falls back to the installed `pyscoped` package's bundled docs).
2. Parses YAML frontmatter for metadata (title, description, category, ordering).
3. Upserts `DocPage` records keyed by file path.
4. Removes `DocPage` records that no longer have a corresponding source file.

### When to Run

- Automatically on every deploy (via the Heroku release phase).
- Manually after updating the pyscoped library version.
- Manually after modifying docs content at `PYSCOPED_DOCS_PATH`.

```bash
# Point to a local checkout of pyscoped docs for development
export PYSCOPED_DOCS_PATH=/path/to/pyscoped/docs
python manage.py sync_pyscoped_docs
```
