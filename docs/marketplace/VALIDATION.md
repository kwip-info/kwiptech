# Validation ledger — September7,2026

Status: implementation validated locally; provider-connected UAT and production cutover pending.
This distinction is deliberate: synthetic success does not prove a live provider integration.

## Automated checks

Python3.13 on Django6.0.8 and5.2.17, PostgreSQL18 and SQLite:

- 335 tests pass on PostgreSQL on each supported Django version.
- 325 tests pass on SQLite;10PostgreSQL-only concurrency cases are skipped there.
- Ruff E/W/F, JavaScript syntax, Django system checks, migration drift and static collection pass.
- OpenAPI3.1 validation and route matching pass.

Tests exercise typed schema evolution, dryrun/apply, append-only revisions/tombstones, batch
replay/conflict, concurrent ingestion, snapshot cursors, query types/projection/budgets,
per-account receipts, Free/Pro boundaries, overage caps, Stripe SDK serialization/signatures,
outbox leases/ambiguity/reconciliation, renewal recovery and queue fairness, key/identity/session
revocation and stale-authority races, source-restricted reads/downloads, transactional exports,
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

Pending: dashboard sign-in, real Stripe sandbox Checkout/portal/cancellation/meter UAT,
Clerk webhook configuration and provider-connected browser sign-in, new provider configuration,
GitHub CI, backup and empty-catalog production validation. Use PROVIDER_SETUP.md and OPERATIONS.md.
`marketplace_preflight --production --require-empty` is a read-only launch gate. Do not claim
completion from this local ledger alone; private enterprise receipts record actual deployments.
