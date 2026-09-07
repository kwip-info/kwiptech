# KWIP Data

A data marketplace for people and agents at [kwip.tech](https://kwip.tech).
Explore dataset metadata, retrieve attributable records through a bounded API,
manage scoped service access, and track Free/Pro credits and optional Stripe overage.
The public catalog remains empty. A bounded, operator-only US jobs POC can collect
one attributed evaluation sample on Heroku; it does not enable customer delivery.
MIT licensed. Canonical repository: https://github.com/kwip-info/kwiptech.
Digest and free Django-only PyScoped remain at [kwip.info/technology](https://kwip.info/technology/).

## Architecture and contracts

- `plane/catalog`: versioned schemas, approved sources, idempotent ingestion and snapshot reads.
- `plane/access`: Clerk sessions, scoped hashed service keys, explicit device approval, revocation.
- `plane/commerce`: credit ledger, Free/Pro allowances, opted-in caps, Stripe outbox/reconciliation.
- `plane/exports`: bounded asynchronous Pro exports and expiring download artifacts.
- `plane/market`: public exploration, API facade and browser account UI.

Start with [agent/API guidance](docs/marketplace/AGENT_GUIDE.md),
[data contract](docs/marketplace/DATA_CONTRACT.md),
[billing contract](docs/marketplace/BILLING_CONTRACT.md),
[export contract](docs/marketplace/EXPORT_CONTRACT.md), and
[operations](docs/marketplace/OPERATIONS.md). The machine-readable API is served at
`/api/v2/openapi.json`; `/agents.txt` explains safe discovery and retry behavior.

The [jobs POC](docs/marketplace/JOBS_POC.md) and
[source manifest](plane/catalog/job_sources.json) record normalization, collection
budgets, attribution, retention and recurring source-review dates.

## Development

Python 3.13, Django 5.2 or 6.0, PostgreSQL 18. Install `requirements-dev.txt` in a
virtual environment, configure `DATABASE_URL` for a dedicated development database,
then run:

```sh
python manage.py migrate
python manage.py runserver
python manage.py run_marketplace_worker
```

SQLite is supported for isolated unit tests, not concurrent account usage or billing.
The local synthetic browser workflow is in [UAT](docs/marketplace/UAT.md).
Use `.env-example` as a reference; Django reads environment variables directly.
No default production credentials or datasets ship. A Django superuser can assign
operator status after the intended Clerk identity has signed in; publisher keys require
explicit dataset and source restrictions.

```sh
python -m pytest -q
python manage.py collectstatic --noinput
python -m pytest --ds=plane.settings -q
python manage.py makemigrations --check --dry-run
```

The second test run uses the configured PostgreSQL database and checks concurrency.
See CI for the Django5.2/6.0 matrix. Do not point tests at production.

## Deployment

GitHub CI tests before deploying main to the existing Heroku app `kwip-tech`.
The release phase runs additive migrations and static collection; scale the worker
explicitly. Preserve database backups before deployment. Keep provider keys, backups,
source records and build artifacts out of this repository. Production receipts belong
in the private enterprise operations repository.

Purchases stay unavailable until approved published sources contain data. Billing
requires new `MARKET_*` price, meter and webhook configuration; old PyScoped prices
never grant marketplace entitlements. Prices are configurable and shown as proposed
while purchases remain closed. Paid overage is disabled by default.

## PyScoped 2.0 cutover

PyScoped is a free Django library with no cloud ingestion or paid tiers.
The former v1 API, dashboard, account provisioning, and billing endpoints return
HTTP 410. Their handlers and scheduled billing commands have been removed.
Historical core/billing models and migrations remain solely to preserve existing
databases and rollback; no historical tables are dropped. The SDK creates its own
additive audit tables. See [migration](docs/sdk/migration.md).

Legacy product and documentation GET/HEAD URLs permanently redirect to their static
kwip.info counterparts. Old Digest submissions return 410 without parsing or storing
the body; the new page uses the existing KWIP Formspree provider. Django staff
administration and historical leads remain available. Legacy redirects and retirement responses require no database. Bundled documentation and old templates remain as historical source only.
