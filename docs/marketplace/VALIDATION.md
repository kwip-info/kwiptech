# Validation ledger — September 7, 2026

Status: automated, browser, real Stripe sandbox and empty-catalog production acceptance passed.
The marketplace deployed September 7, 2026; paid purchases remain gated while the catalog is empty.

## Automated checks

Python 3.13 on Django 6.0.8 and 5.2.17, PostgreSQL 18 and SQLite:

- 352 tests pass on PostgreSQL and 342 on SQLite for the final portal configuration change;
  10 PostgreSQL-only concurrency cases are skipped on SQLite. CI checks both supported Django versions.
- Ruff E/W/F, JavaScript syntax, Django system checks, migration drift and static collection pass.
- OpenAPI 3.1 validation and route matching pass.
- PR #2 and main CI run 34164768751 passed, including production deployment and live route smoke checks.

Tests exercise typed schema evolution, dryrun/apply, append-only revisions/tombstones, batch
replay/conflict, concurrent ingestion, snapshot cursors, query types/projection/budgets,
per-account receipts, Free/Pro boundaries, overage caps, Stripe SDK serialization/signatures,
outbox leases/ambiguity/reconciliation, renewal recovery and queue fairness, key/identity/session
revocation and stale-authority races, verified TLS for JWKS discovery, read-only staff diagnostics
that exclude sensitive payloads, source-restricted reads/downloads, transactional exports,
expiry cleanup, CSV formula safety, operator authorization, and the preserved retired endpoints.
Stripe tests use controlled transports; they do not move money or contact live customers.

## Browser acceptance

Used real browser navigation and controls against isolated PostgreSQL synthetic fixtures.

- Catalog, metadata/schema/evidence, navigation to pricing/API/account/privacy and return links.
- 25record page costs50credits; second page50more; empty exact filter0credits.
- Deliberately lost a response after commit; Retry reused the request ID and returned the original
 receipt. Four total receipts (three25record deliveries plus one empty) totaled150credits.
- Created/hid/revoked a fixture key; browser clearly labels it revoked.
- Device flow displayed scope, approved a local agent, issued one token; second poll refused.
- Pro JSONL export prepared63records for126credits and authenticated download succeeded.
- CSV export with10credit budget produced5records, stopped partial, and exposed a download.
- 390pixel child browsing context exercised responsive catalog/query/export/account controls.
 This uses a same-origin frame only in UAT because the browser host ignored viewport overrides.
 Production continues denying framing. Wide tables remain horizontally scrollable.

The UAT suite has no external data or payment credentials. Its source is excluded from Heroku
slugs. Production must use `plane.settings`/`plane.urls` and have no `/_uat/*` routes.

## Provider and release gates

Production Clerk sign-in succeeded through the real Account Portal. The signed lifecycle endpoint
accepted a provider sample session-ended event and persisted its session tombstone. A real signed-in
workspace created and revoked read keys and approved a device connection; the issued key read usage,
was refused browser-only billing and operator writes, and returned 401 after revocation. Repeated
device polling refused a second token. Both temporary production keys were revoked.

Real Stripe sandbox acceptance passed: hosted Checkout reported paid, application reconciliation
granted Pro, 10,000 overage credits appeared in Stripe's meter summary, replay/cap protection held,
and the dedicated portal scheduled cancellation while preserving paid access through period end.
A provider-generated, CLI-forwarded webhook passed signature verification and reconciliation.
Identity-deletion cleanup canceled the test subscription without immediate invoicing or proration.
No real funds moved. The immediate meter summary check does not replace delayed reconciliation.

Browser acceptance also verified the empty catalog and unavailable Pro purchase state, ordinary
staff denial, the denial-page return link, and superuser receipt inspection without cached records
or edit controls. A restored production backup passed additive migrations with historical table
counts preserved and all new marketplace tables empty.

Production preflight passed with billing configured and zero datasets, sources, records, revisions,
ingestion batches or exports. The web and bounded marketplace worker are running. Live prices and
the sum meter passed application validation. A genuine Stripe product-created event for the new
marketplace product passed the live webhook signature check; its temporary event subscription was
removed afterward. No live customers, subscriptions or test charges were created.

Public catalog, API guide, pricing, account, policy pages, OpenAPI and agent instructions return
successfully. The catalog is explicitly empty and the plans API reports purchases unavailable.
Retired API routes remain 410; Digest/PyScoped redirects remain intact; production UAT routes are 404.
Use PROVIDER_SETUP.md and OPERATIONS.md for source activation and ongoing operations. Private
enterprise receipts retain backup, provider configuration, deployment and rollback evidence.
