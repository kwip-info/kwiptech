# Catalog and ingestion contract

The marketplace stores versioned JSON records against explicitly registered typed schemas.
“Register a table” creates a dataset and schema, never a dynamic SQL table or executable query.
There are no automatic production seeds or collection schedules. Registration and
batch ingestion are operator capabilities, separate from customer read credentials.
The separately invoked jobs POC connector performs one bounded hosted fetch;
registration and batch ingestion themselves never fetch source URLs.

## Repeatable registration

`python manage.py register_dataset manifest.json --dry-run` validates the full manifest in
one rolled-back transaction. Remove `--dry-run` to apply. Reapplying identical registration
updates no logical identity; slugs identify datasets and sources. Existing schema definitions
are immutable. Evolution is additive: preserve existing fields, scalar types, and enum values.
Add a new positive `schema_version` for changes and explicitly switch a source.
A new dataset starts draft. Register and approve its sources before separately publishing it.

```json
{
  "slug": "synthetic-example",
  "title": "Synthetic example",
  "category": "test",
  "status": "draft",
  "credits_per_record": 1,
  "schema_version": 1,
  "fields": {
    "title": {"type": "string", "required": true},
    "amount": {"type": "number"},
    "state": {"type": "enum", "values": ["open", "closed"]}
  },
  "sources": [{
    "slug": "example",
    "name": "Synthetic source",
    "url": "https://example.com/data",
    "schema_version": 1,
    "rights_status": "pending"
  }]
}
```

Supported scalar types are string, integer, finite number, boolean, timezone-aware ISO datetime,
ISO date, and string enum. Fields are named lower-case identifiers, maximum 100 per schema.
Unknown fields and null values are rejected; omit optional values. Integers are signed 64-bit,
strings at most 100,000 characters. There are no arbitrary SQL expressions or nested objects.

Approval requires attribution and a license/evidence URL. This records an operator decision,
not automated legal verification. Source discovery alone never implies permission to redistribute.
Before approval, operators must review licensing, privacy, robots.txt, access terms, rate limits,
and retention requirements. Inactive, pending, or blocked sources cannot ingest or deliver data.
The separate `evaluation` rights status permits ingestion only into draft datasets,
with attribution/evidence required. It is not approved commercial redistribution;
public reads, exports and purchase availability still require `approved` sources.
Only browser-authenticated KWIP operators can inspect the private jobs POC preview.
Published datasets must have an active approved source; withdrawal immediately stops public reads.
Admin is trusted operator access. Bulk ORM updates bypass Django validation and are not a supported
registration interface; use services, commands, or the validated admin forms.

## Batch ingestion

`python manage.py ingest_dataset synthetic-example example batch.json --idempotency-key RUN_ID --dry-run`
accepts a JSON list from a file or `-` for stdin. It never retrieves the source URL.

```json
[{
  "external_id": "stable-upstream-id",
  "payload": {"title": "Synthetic item", "amount": 12.5, "state": "open"},
  "observed_at": "2026-09-07T12:00:00Z",
  "effective_at": "2026-09-01T00:00:00Z",
  "source_url": "https://example.com/data/stable-upstream-id"
}]
```

Batches contain 1–500 unique external IDs and at most 2 MB canonical JSON. All items validate
before any writes. A database transaction atomically creates the receipt and versions. Errors
leave no partial records or successful receipt. Clients can retry after transient failure using
the same source and key. An exact canonical-input replay returns the original receipt; conflicting
input for an existing key fails. JSON object order is immaterial; list order is significant.
Dry runs validate and write nothing. A replay of an already committed batch returns its receipt
even when dry run is requested.

Identity is `(source, external_id)`. Each successful new batch creates an immutable observation
version, even when content is unchanged; equal content shares the same hash. This deliberately
preserves “last observed” evidence. Updates from another source never overwrite that identity.
Each version retains its schema, ingestion batch, observation/effective timestamps, source URL,
and content hash. Ingestion order defines the latest revision, not the upstream timestamp;
backfills must account for this explicitly. A tombstone has `tombstone: true` and empty payload;
it hides the record from latest reads while retaining historical evidence. A later observation
can restore it. Deletion/erasure obligations need a separate reviewed retention procedure.

## Customer reads and reproducible exports

`read_records(dataset, filters={}, limit=100, cursor=None, fields=None)` returns records, the
page count, snapshot watermark, and an opaque next cursor. Each result carries `data`, identity,
revision, source attribution/license, source URL, schema version, timestamps, and hash. The service
never charges; the API layer authorizes and atomically meters records actually returned.

Filters are exact scalar equality on named fields in the newest registered schema, maximum ten.
Projection accepts unique named fields. Limit is 1–100. No raw SQL, lookup operators, offsets, or
unbounded count query is exposed. `count` means this page's delivered records, not a dataset total.
JSON field equality uses database-native JSON equality. Date/datetime values should be normalized
by the connector because different equivalent datetime strings are distinct equality values.

Pages are ordered by stable record ID. A signed 24-hour cursor binds dataset, filter, projection,
last ID, query schema ID, and a committed revision watermark. Schema validation remains pinned
to that original query schema even when a new version is registered. Subsequent pages select each record's latest version
at or before the watermark, so concurrent new records/updates do not move a snapshot. Changing
limit is allowed. Changing filters or projection requires a new export. Source rights and dataset
publication are always checked live: a revocation can intentionally remove rows from an existing
export. Attribution and license evidence are snapshotted with each revision; immutable
version payload/schema/URLs/timestamps preserve the historical evidence. This safety exception takes precedence over reproducibility.

## Scale decisions and next thresholds

A per-dataset database lock serializes ingestion and each bounded read, including snapshot
watermark acquisition. Different datasets can operate independently, but a busy dataset has
one concurrent catalog transaction: this is a deliberate initial throughput ceiling. This makes
PostgreSQL committed revision ordering reliable without long-lived export transactions. Read
transactions are bounded to 101 selected results; retries on lock contention belong in callers.
SQLite is for local tests; PostgreSQL is the production concurrency boundary.

The indexed `(record_id, revision_id)` history supports latest-revision lookup. JSON filters can
still scan as collections grow. Before large ingestion, measure production query plans, add
reviewed PostgreSQL expression/GIN indexes for known demand, and consider materialized current
records plus snapshot export jobs. Do not let connectors create arbitrary indexes or SQL. Batch
limits bound request memory, not total collection size. The bounded jobs POC now supplies
one source adapter, durable request reservations, retry timing and seven-day evaluation
retention. Broader scheduling, paid-source credentials and source-specific deletion
policies remain later connector work. POC retention is an explicit exception to the
ordinary retained marketplace revision history above.
