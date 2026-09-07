# KWIP Technology

Public Django website for [kwip.tech](https://kwip.tech): free PyScoped 2.0
integration documentation and Digest product information/pilot intake.
MIT licensed. Canonical repository: https://github.com/kwip-info/kwiptech.

## PyScoped 2.0 cutover

PyScoped is a free Django library with no cloud ingestion or paid tiers.
The former v1 API, dashboard, account provisioning, and billing endpoints return
HTTP 410. Their handlers and scheduled billing commands have been removed.
Historical core/billing models and migrations remain solely to preserve existing
databases and rollback; no historical tables are dropped. The SDK creates its own
additive audit tables. See [migration](docs/sdk/migration.md).

Digest pilot intake and Django staff administration remain available. Public pages
and retirement responses do not require a database. Docs are bundled with the
release, so web startup does not download mutable documentation from PyPI.

## Development

Python 3.13, Django 5.2 or 6.0. Create a virtual environment, install
`requirements-dev.txt`, then set `DATABASE_URL=sqlite:///db.sqlite3` and run:

```sh
python manage.py migrate
python manage.py runserver
python -m pytest -q
python manage.py makemigrations --check --dry-run
```

Use `.env-example` as a reference; Django reads environment variables directly.
For staff access use Django's `createsuperuser`; no default credentials ship.

## Deployment

GitHub CI tests before deploying main to the existing Heroku app `kwip-tech`.
The repository rename does not rename Heroku or change kwip.tech DNS.
Configure `SECRET_KEY`, `DEBUG=False`, `ALLOWED_HOSTS`, and `DATABASE_URL` in Heroku.
The release phase migrates additively and collects static files.
Do not put tokens, database backups, or production records into this repository.
Production backup/cutover/rollback evidence belongs in the private enterprise
operations repository. Retain Heroku backups before deployment.
