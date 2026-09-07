# Marketplace operations

## Empty launch and responsibilities

This release supplies catalog registration, ingestion, scoped access, accounting and export
machinery. It does not ship production datasets, seed records, run external crawlers or schedule
source ingestion. Keep datasets draft and sources pending until redistribution rights and
connector requirements are reviewed. A source inventory is research, not ingestion authorization.
PyScoped's retired endpoints remain retired; the marketplace uses its own versioned API and
identity/accounting tables. Historical account and billing tables are preserved.

The Procfile provides web, release and worker process types. Release performs additive migrations
and static collection. The worker uses `python manage.py run_marketplace_worker`; production must
explicitly scale that process to one running worker before advertising asynchronous exports.
Adding a Procfile entry alone does not start a Heroku dyno. One worker is the initial supported
operational topology. Multiple workers are protected by export locks/outbox leases, but can
perform redundant reconciliation and should not be used as a throughput strategy without review.

## Worker cadence and bounded execution

The unified worker performs four independent responsibilities:

| Responsibility | Minimum interval after completion | Default batch |
| --- | --- | --- |
| Export preparation | 10 seconds | 25 distinct jobs/pages, at most100 records/page |
| Due Stripe usage dispatch | 30 seconds | 25 events |
| Webhook/subscription/meter reconciliation | 5 minutes | 25 events and25 accounts |
| Artifact, response cache, device grant and rate-window cleanup | 5 minutes | 25 rows per category |

`--limit 1–100` changes each task batch. The loop sleeps5seconds between readiness checks; intervals
are minimum gaps after completion, so provider latency cannot create a catch-up request burst.
Each export gets at most one page per selected batch so failing jobs cannot starve healthy peers.
There is no busy loop. Work remains durable in the database across restarts. Long-running tasks
can delay subsequent responsibilities; monitor queue age and split workers before this becomes
material. Retain a single worker until such evidence appears.

`python manage.py run_marketplace_worker --once --limit 10` runs every responsibility once and
exits nonzero if any fails. It continues other responsibilities after a task failure, so a billing
problem does not prevent expiry cleanup. Logs name the task and exception type without dumping
provider errors, request bodies, secrets or exported records. Inspect durable status/error codes
and the provider dashboard when diagnosing a failure. Do not copy credentials into logs.

No Stripe provider traffic occurs unless billing is enabled and the secret key plus both price
IDs are configured. Disabling billing pauses dispatch and reconciliation, retaining their durable
records. Do not assume pausing billing settles outstanding obligations. Before resuming, inspect
pending/review outbox rows and mismatched meter reconciliations. Account entitlement cannot be
trusted to refresh while reconciliation is paused; subscription dates still bound access locally.

Standalone commands remain available for deliberate recovery:

```sh
python manage.py process_exports --once --limit 25
python manage.py cleanup_exports --limit 100
python manage.py purge_delivery_cache --limit 1000
python manage.py dispatch_usage --limit 25
python manage.py reconcile_billing --limit 25
```

Unlike the unified worker, standalone billing commands are explicit operator actions and rely on
the gateway's credential/environment validation. Do not run them against production casually.

## Export and cache recovery

Default per-artifact ceilings are10,000 records,10MiB output and an explicit user budget capped at
1,000,000 credits. At most20 unexpired jobs exist per workspace. Users see partial status if a cap
stops preparation before exhaustion. Charges apply to prepared records, not download attempts.
The detailed contract is EXPORT_CONTRACT.md. Never tell customers a partial artifact is complete.

Job, output chunk and billing receipt commit atomically per page. A process interruption retries
the same page without duplicate output or usage. Transient unexpected failures leave the job
retryable; authorization/rights/expiry and budget failures become terminal. Review `error_code`.
Do not edit a completed job's cursor/counters or delete financial receipts to “retry.” Correct the
underlying issue and create a new deliberate request ID when new preparation is intended.

Artifacts and replay payloads expire after24hours. Cleanup removes expired jobs/chunks and clears
raw Commerce delivery responses. Accounting/idempotency receipts remain; replay after expiry fails
rather than charging again. Cleanup is bounded, so expiration blocks access immediately while
physical deletion can lag behind a backlog. Monitor oldest expired artifact/cache age and increase
batch size or run a bounded catch-up command if needed. Device grants delete after expiration;
rate buckets delete only when their window is over24hours old. Live windows, service keys and
identity records are not deleted by maintenance.

For large collections, move artifacts to private object storage with lifecycle rules before
raising local DB limits. Current Commerce replay caching duplicates page data temporarily; allow
for both chunks and delivery payloads in storage estimates. A user or source-rights withdrawal
blocks download and further preparation immediately at the next authorization check.

## Stripe ambiguity and reconciliation

Local deliveries are the usage authority. MeterOutbox delivery IDs are stable event identifiers
and Stripe idempotency keys. Dispatch selects only due, unleased records; backoff and customer
leases avoid routine duplicate submits. It never fabricates a replacement event ID for retries.

An ambiguous event whose first attempt is23hours old moves to `review`, before the expected remote
deduplication boundary. A non-retryable provider response also requires review. **Do not reset
these rows to pending, change their identifiers, or submit a new charge without investigating
Stripe acceptance and local receipts.** The correct recovery is reconciliation and a recorded
operator decision. A remote timeout is not evidence that a charge was rejected.

Meter reconciliation compares settled windows ending at least15minutes ago. `unsettled` means
outbox delivery is incomplete; `mismatch` requires investigation. Reconciliation records evidence
and never silently creates compensating charges. Multiple pagination pages or provider ambiguity
requires operator review. Webhook processing fetches current subscription state instead of trusting
out-of-order event payloads as entitlement authority.

## Verification and rollback

Before deployment: migrate a restored disposable database, run SQLite and PostgreSQL tests,
exercise `--once` with billing disabled, and browser-test sign-in, empty catalog, API-key access,
usage messaging and export limits with synthetic data only in a disposable environment. Production
must remain empty until separately authorized source ingestion is ready.

Before changing a production deployment, take/verify a database backup and record the prior release.
Keep marketplace migrations additive. A code rollback does not undo financial events or delete
new records. If necessary pause sales and the worker, preserve durable queues, restore the prior
compatible code and investigate before resuming. Never restore a database backup over financial
activity without an explicit reconciliation plan. Production receipts, cutover evidence and
incidents belong in the private enterprise operations repository, not this public code repository.

## Staff billing diagnostics

Django `/admin/` exposes a **superuser-only, read-only** Commerce diagnostics section. Marketplace
customer identities and operator flags do not confer Django admin access. Ordinary staff users
cannot view these diagnostics even if someone assigns individual Commerce model permissions.
There are no add/change/delete permissions or bulk mutation actions, including for superusers.

Use BillingAccount to inspect current entitlement, period, overage consent/cap and reconciliation
or cancellation timestamps. Delivery provides workspace/dataset/request identifiers, delivered
record/credit counts, applied price and billing window. MeterOutbox shows pending/submitted/review
status, attempts, next retry, lease and sanitized error code; MeterReconciliation shows expected
versus remote totals. StripeEvent exposes only event ID/type/status/timestamps/error code, while
BillingConsent shows the recorded consent policy, actor, cap and rate. Search exact workspace or
provider IDs and filter status/time to narrow an incident. Lists are paginated50rows.

Cached record responses, raw webhook payloads and checkout URLs/tokens are explicitly excluded
from forms, lists and search, and deferred from diagnostic database reads. No provider credentials
are exposed. These pages are inspection tools, not a way to repair or resend billing. Follow the
reconciliation/recovery procedures above and record consequential corrections in private operations.
