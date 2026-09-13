# Heroku slideshow runtime

Owner: Trevor Ewert. App: kwip-tech. Domain: https://kwip.tech.
On September 13, 2026 the owner explicitly authorized production deployment and
removal of the former marketplace database. The enterprise cutover receipt owns
release IDs, backup details and actual completion status.

## Deployment

GitHub main CI tests the historical code plus the slideshow runtime on Django 5.2
and 6.0, validates the catalog, collects static files, then pushes the tested SHA to
the existing Heroku app. The Procfile runs `gunicorn show.wsgi:application` and a
static-only release phase. There is no database, worker, billing or Clerk runtime.
Runtime dependencies are Django, Gunicorn, WhiteNoise and certifi. Historical
marketplace dependencies are installed only by requirements-dev.txt for regressions.

Smoke-test home, `/about/content`, `/healthz`, `/api/slides/catalog`, both JavaScript
assets, a remote image slide, a generated local image, clicker navigation and credits.
The catalog must contain at least 892 items. Old marketplace APIs and integrations
return 410; historical product/docs redirects and the domain remain unchanged.

## Initial retirement sequence

Record current release, SHA, formation and configuration. Check actual subscriptions,
billing events and exports. Capture a database backup, download it outside git with
restricted permissions, and verify full `pg_restore` archive decoding. Stop the old
worker. Deploy and verify the replacement before destroying the database add-on.
Disable only the old kwip.tech Stripe webhook endpoints and retire their prices;
leave shared provider accounts intact. Remove unused app-specific provider config.
Record every mutation in enterprise operations.

## Recovery

For a slideshow release regression, use the previous compatible slideshow release
with `heroku releases:rollback vNN -a kwip-tech`. No database is needed.

Returning all the way to the marketplace after database retirement requires a new
Postgres add-on, restoration of the retained dump with `pg_restore`, restoration of
the restricted configuration snapshot, deployment of the recorded pre-cutover SHA,
and restoration of worker formation and provider endpoints. Merely rolling back a
slug cannot recreate a deleted database or restore external provider configuration.
Never write the backup, configuration snapshot or credentials into this repository.
