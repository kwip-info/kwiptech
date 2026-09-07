# Pro export contract

Exports prepare a bounded, reproducible dataset snapshot asynchronously. They are not unbounded
SQL downloads. No records ship with the application. An active Pro account, `datasets:read`, and
`exports:read` are required; normal service-key dataset restrictions still apply.

## HTTP and consent

`POST /api/v2/exports` requires Bearer authentication, an explicit `Idempotency-Key`, and JSON:

```json
{"dataset":"registered-slug","filters":{},"format":"jsonl","max_credits":1000}
```

Submitting this request authorizes preparing records up to `max_credits`. The UI must explain
that **credits are consumed when records are prepared, even if never downloaded**. Downloading
an existing artifact adds no charge. Normal included-credit, overage opt-in, and monthly spend
caps still apply. `max_credits` is an additional per-export ceiling, not consent to enable overage.
No matching records or a draft/withdrawn dataset produces an error without a job or delivery charge.

Creation returns HTTP202 with job metadata. `GET /api/v2/exports` lists up to20 accessible recent jobs;
`GET /api/v2/exports/{id}` returns status; `/api/v2/exports/{id}/download` returns an attachment.
Metadata contains `id,dataset,status,format,rows,credits,max_credits,bytes,snapshot,expires_at,
error_code,download_ready,notice`. Status is queued, running, complete, partial, or failed.
A partial artifact is explicitly marked in metadata and the `X-Export-Status` download header.
Never label a partial export as complete.

The durable request receipt binds workspace, caller identity/key, request ID, dataset, filters,
format and budget. Exact retries return the original job. Changed input fails409. After artifact
cleanup the receipt remains and the same request ID fails410; a retry cannot silently buy a new
export. A new deliberate export needs a new request ID.

## Worker and correctness

`python manage.py process_exports --once --limit 100` processes at most100 pages. Without `--once`
it polls continuously. Each page contains at most100 records. Workers lock the job, workspace,
dataset and relevant sources in a consistent order. Source/key/account checks run before each
page. A page's Commerce delivery receipt, meter outbox if applicable, output chunk, cursor and
counters commit in the same transaction. A crash rolls everything back; retries use the same
job/page delivery ID. Concurrent workers cannot double-charge or append duplicate chunks.

Creation persists the catalog's signed start cursor, query schema, committed snapshot watermark,
and approved source IDs. Later ingestion does not change the selected snapshot. Query schema
and provenance behavior follow DATA_CONTRACT.md. Every page rechecks the original service key,
its current scopes/restrictions, account status, dataset publication and source rights. Deleted,
revoked or expired creator keys fail closed even if the workspace owner later requests download.
The original restrictions are retained as job audit evidence. Browser-created jobs are bound to
the workspace owner. Cross-workspace lookups return404.

Downloads recheck both the requester and original job authority, dataset and all captured source
approvals. Withdrawal blocks already-prepared data. A source approval added later does not expand
the original snapshot. All API responses and attachments use `Cache-Control: no-store`.

## Limits, formats and retention

Defaults configurable through Django settings:

- `MARKET_EXPORT_MAX_ROWS`:10,000 records per artifact.
- `MARKET_EXPORT_MAX_BYTES`:10MiB UTF-8 output per artifact.
- `MARKET_EXPORT_MAX_CREDITS`:1,000,000 maximum requested credits.
- `MARKET_EXPORT_MAX_JOBS`:20 unexpired jobs per workspace.

Rows/budget exhaustion produces partial status if more pages remain. Byte or quota limits stop
before committing the rejected page; existing chunks remain downloadable as partial. If the
first page cannot fit, status is failed and nothing is charged. Large individual records can
also reach Commerce's1MiB per-page response bound. These ceilings deliberately bound local DB
artifact storage; they are not a promise to export arbitrarily large datasets. The next scaling
step is private object storage plus streaming manifests, lifecycle rules, integrity hashes and
leased workers, retaining the same atomic accounting/visibility contract.

JSONL retains structured records and provenance faithfully. CSV contains a header, identity,
revision, source slug/URL, observation timestamp and schema fields. Formula-like strings receive
a leading apostrophe (including whitespace-prefixed formulas) to reduce spreadsheet execution
risk. CSV is a convenience projection; JSONL is the format for complete provenance.

Artifacts expire24hours after creation, matching cursor validity. Run
`python manage.py cleanup_exports --limit 100` regularly; it removes at most100 expired jobs and
their chunks each run. Request deduplication receipts and Commerce audit/delivery records remain.
Commerce's cached delivery payload retention is governed separately; deleting an export artifact
does not assert that every financial/audit copy has been erased. No filesystem paths or external
source credentials are accepted by this interface.
