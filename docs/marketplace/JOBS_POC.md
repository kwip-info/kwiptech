# US jobs aggregation POC

Owner: KWIP Technology. Started September 7, 2026 under the user's jobs-only,
US-first direction. This is a bounded experiment within the existing marketplace.
Other dataset acquisition remains deferred.

## Phases and gates

1. Source manifest and permission boundaries. Use a free, attributed source whose
   API explicitly permits internal dashboards. Separate evaluation from commercial
   redistribution approval. Gate: expired/pending/blocked policies cannot collect;
   evaluation records cannot reach the public catalog, customer reads or exports.
2. Bounded connector and normalization. One US-specific Himalayas search response,
   no pagination, no descriptions/logos, no local real-data ingestion. Preserve IDs,
   provenance, salary period and timestamp semantics. Gate: synthetic tests for
   malformed data, US eligibility, request limits, robots, retries and idempotency.
3. Private review UI and hosted sample. Operators inspect standardized rows and
   sample-quality summaries. Gate: browser UAT, unauthorized-access checks, one
   real hosted collection, repeat invocation makes no extra source request.
4. Repeatability and handoff. Durable request receipts, next refresh/review times,
   retention, candidate sources and discovery cadence. Gate: documented command
   and manifest support consistent updates without silently enrolling new sources.

## Decisions

Why Himalayas? Its API permits internal dashboards and agent workflows with
attribution. General site terms are restrictive; this POC does not approve paid
redistribution or full exports. Evidence: https://himalayas.app/api,
https://himalayas.app/docs/openapi.json, https://himalayas.app/terms.

Why factual normalization? It produces comparable employer, eligibility and pay
fields while minimizing copied expression. Transformation is useful product work,
not an automatic fair-use determination or an override of source conditions.
The US Copyright Office describes a case-specific four-factor inquiry:
https://www.copyright.gov/fair-use/.

Why one response? It tests the real pipeline cheaply and limits upstream load.
It is a current sample of remote postings explicitly including the US, not a
representative US labor-market dataset or a historical archive. Missing records
do not imply closure. No salary annualization or fabricated company identity.

Why separate evaluation rights? A successful fetch must never silently grant
customer access. The dataset stays draft; publication requires a separate source
rights decision. Browser viewing is limited to signed-in KWIP operators.

Collection cadence: at most daily, manual activation for this POC. The source
manifest records weekly discovery and permission review. No automatic enrollment,
paid source subscription, supplier outreach or public data publication is included.
Real collection runs only in the hosted runtime; local tests use invented records.

## Operator workflow

The authoritative manifest is `plane/catalog/job_sources.json`. It includes one
evaluation source and six pending candidates. Its review date is a hard collection
and preview gate; update it only after checking the linked current policies.

```sh
# Offline plan: no database writes or source traffic.
python manage.py collect_jobs_poc
# Hosted execution: one robots request and at most one data request.
heroku run 'python manage.py collect_jobs_poc --collect' -a kwip-tech
```

The second invocation before the persisted `next_allowed_at` returns `not_due`
without any source traffic. A 429/503 can extend this time through Retry-After.
Redirects, inaccessible/disallowing robots and stale permissions stop collection.
There is no bypass or automatic retry loop. Search pagination is deliberately
absent because the current robots policy disallows page-query patterns.

Inspect `/account/jobs-poc` from the existing operator account. Its authenticated
GET `/api/v2/operator/jobs-poc` returns at most the latest sample plus ten audit
receipts. No customer credit is debited. Ordinary service keys cannot use this
browser-only evaluation endpoint. Original descriptions/excerpts/logos are neither
retained nor shown. Raw responses are discarded after in-memory normalization.

The existing worker removes expired POC payload versions in bounded batches,
including after source revocation. Audit receipts retain counts and error codes,
not source bodies. Freshness is shown as observation time; source expiry is not
proof of hiring. Collection policy review also hides old samples until reviewed.

Scheduling is prepared, not activated: minimum daily collection interval and
weekly discovery cadence are recorded separately. Source discovery may update
evidence and pending candidates; it cannot silently turn a source on. This POC
does not run a crawl on every browser view or create a supplier subscription.

## Validation so far

- SQLite: 375 passed, 10 existing PostgreSQL-only skips before the additional
  concurrency test; final exact counts recorded in the private release receipt.
- PostgreSQL: 386 passed, including a simultaneous first-collection test proving
  that only one request budget is consumed.
- Static lint, JavaScript syntax, migration drift and static collection passed.
- Synthetic browser UAT: customer denied; operator account link/back navigation;
  two normalized rows with annual/hourly pay; search and empty state; source links;
  390px layout with contained scrolling tables. Fixtures contain no real source data.
- Independent review caught and fixed withdrawal retention, robots 503 retry timing
  and product-token matching; regression tests cover all three.

## Rollback and stop conditions

Disable the source or withdraw the draft dataset to hide the preview and reject
new collection. The request reservation and rows remain for audit/retention.
If rolling the application back to a release without the POC cleanup worker,
first expire the evaluation rows using the current cleanup function with a future
cutoff, then verify zero POC versions. Preserve a database backup before migrations;
the schema changes are additive and need not be reversed for a code rollback.
No source data is committed to Git. Production receipts belong to the private
enterprise operations repository.
