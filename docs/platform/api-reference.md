---
title: REST API Reference
description: Complete reference for all pyscoped platform v1 API endpoints, authentication, request/response formats, and error handling.
category: Platform API
---

# REST API Reference

Base URL: `https://kwip.tech/v1`

All request and response bodies use JSON (`Content-Type: application/json`).

---

## Authentication

API keys use the Bearer token scheme:

```
Authorization: Bearer psc_live_a1b2c3d4e5f6...
```

### Key Format

Keys follow the pattern `psc_{environment}_{hex}`:

| Segment       | Description                                      |
|---------------|--------------------------------------------------|
| `psc`         | Static prefix identifying a pyscoped key.        |
| `live`/`test` | Environment the key is scoped to.                |
| `{hex}`       | 32-byte random hex string (64 characters).       |

### Storage and Lookup

Keys are **never stored in plaintext**. On creation the raw key is shown exactly once. The platform stores a SHA-256 hash of the full key string. Authentication performs a hash-then-lookup:

```python
import hashlib

incoming_key = "psc_live_a1b2c3..."
key_hash = hashlib.sha256(incoming_key.encode()).hexdigest()
# SELECT * FROM api_keys WHERE key_hash = %s AND is_active = true
```

Every successful authentication updates `last_used_at` on the matching `ApiKey` record so operators can identify stale credentials.

---

## Endpoints

### `GET /v1/ping`

Health check. No authentication required.

**Response `200 OK`**

```json
{
  "ok": true,
  "server_time": "2026-03-31T18:42:07.123456Z",
  "api_version": "v1"
}
```

Use this endpoint for uptime monitoring and connectivity checks from the SDK before starting a sync cycle.

---

### `POST /v1/sync/batch`

Ingest a batch of audit entries produced by the SDK agent.

**Authentication:** Bearer API key (live or test).

#### Request Body (`SyncBatch`)

| Field             | Type     | Required | Description                                                        |
|-------------------|----------|----------|--------------------------------------------------------------------|
| `batch_id`        | `string` | Yes      | Client-generated UUID. Used for idempotent deduplication.          |
| `first_sequence`  | `int`    | Yes      | Sequence number of the first entry in this batch.                  |
| `last_sequence`   | `int`    | Yes      | Sequence number of the last entry in this batch.                   |
| `chain_hash`      | `string` | Yes      | Rolling SHA-256 hash of the chain up to `last_sequence`.           |
| `content_hash`    | `string` | Yes      | SHA-256 hash of the serialized entries array.                      |
| `signature`       | `string` | Yes      | HMAC-SHA256 signature of `content_hash` using the API key.         |
| `sdk_version`     | `string` | Yes      | Semantic version of the pyscoped SDK that produced this batch.     |
| `entries`         | `array`  | Yes      | Array of `AuditEntry` objects (see below).                         |
| `resource_counts` | `object` | Yes      | Snapshot of current resource counts (`objects`, `principals`, `scopes`). |

**`AuditEntry` object**

| Field             | Type     | Description                                  |
|-------------------|----------|----------------------------------------------|
| `sequence`        | `int`    | Monotonically increasing sequence number.    |
| `actor_id`        | `string` | Identifier of the acting principal.          |
| `action`          | `string` | Action name (e.g. `object.create`).          |
| `target_type`     | `string` | Resource type of the target.                 |
| `target_id`       | `string` | Identifier of the target resource.           |
| `timestamp`       | `string` | ISO 8601 timestamp from the SDK.             |
| `hash`            | `string` | SHA-256 hash of this entry.                  |
| `previous_hash`   | `string` | Hash of the preceding entry (chain link).    |
| `scope_id`        | `string` | Scope under which the action occurred.       |
| `parent_trace_id` | `string` | Optional trace ID for distributed tracing.   |
| `metadata`        | `object` | Optional key-value metadata.                 |

#### Response `201 Created` (`SyncBatchAck`)

```json
{
  "batch_id": "b7e5c2a1-...",
  "accepted": true,
  "entries_accepted": 50,
  "server_sequence": 1050,
  "received_at": "2026-03-31T18:43:00.000000Z"
}
```

#### Error Responses

| Status | Condition                      | Detail                                                                 |
|--------|--------------------------------|------------------------------------------------------------------------|
| `400`  | Validation failure             | Missing fields, sequence gap, content hash mismatch, invalid signature.|
| `402`  | Plan limits exceeded           | Free tier: hard reject. Paid tier: soft limit with `overage_allowed`.  |
| `429`  | Sync interval too short        | Time since last batch is less than `min_sync_interval_seconds`.        |

#### Deduplication

The platform deduplicates by `batch_id`. If a batch with the same `batch_id` has already been accepted, the server returns `201` with the original `SyncBatchAck` without re-processing. This makes retries safe from the SDK side.

#### Plan Limit Enforcement

- **Free tier** (`free`): Hard limits. When `resource_counts` exceed `max_objects` or `max_principals`, the batch is rejected with `402`. The SDK must reduce resource usage before syncing again.
- **Paid tiers** (`starter`, `team`, `enterprise`): Soft limits. Batches are accepted even if counts exceed included amounts, and the overage is tracked for metered billing at the end of the period.

#### Sync Interval

Each plan defines a `min_sync_interval_seconds`. The platform tracks the timestamp of the last accepted batch per account. If a new batch arrives before the interval has elapsed, it is rejected with `429` and a `Retry-After` header:

```
HTTP/1.1 429 Too Many Requests
Retry-After: 12
Content-Type: application/json

{
  "error": "sync_interval",
  "message": "Minimum sync interval not met. Retry after 12 seconds.",
  "details": {
    "min_interval_seconds": 30,
    "seconds_remaining": 12
  }
}
```

---

### `POST /v1/sync/verify`

Verify chain integrity between the SDK's local state and the platform's stored state.

**Authentication:** Bearer API key.

#### Request Body

| Field               | Type     | Required | Description                                    |
|---------------------|----------|----------|------------------------------------------------|
| `local_chain_hash`  | `string` | Yes      | The chain hash computed locally by the SDK.     |
| `local_entry_count` | `int`    | Yes      | Total number of entries the SDK has recorded.   |

#### Response `200 OK`

```json
{
  "verified": true,
  "server_chain_hash": "a3f8b2...",
  "server_entry_count": 1050,
  "local_chain_hash": "a3f8b2...",
  "local_entry_count": 1050,
  "first_mismatch_sequence": null
}
```

When `verified` is `false`, `first_mismatch_sequence` indicates the earliest entry where the chain diverges. The SDK can use this to identify the point of corruption or data loss.

```json
{
  "verified": false,
  "server_chain_hash": "a3f8b2...",
  "server_entry_count": 1050,
  "local_chain_hash": "d4e1c7...",
  "local_entry_count": 1048,
  "first_mismatch_sequence": 999
}
```

---

### `GET /v1/keys`

List all API keys for the authenticated account.

**Authentication:** Bearer API key or Clerk session.

#### Response `200 OK`

```json
[
  {
    "key_id": "key_01HXY...",
    "key_prefix": "psc_live_a1b2",
    "environment": "live",
    "label": "Production SDK",
    "is_active": true,
    "created_at": "2026-01-15T10:00:00Z",
    "last_used_at": "2026-03-31T18:40:00Z"
  }
]
```

The full key value is never returned. Only the `key_prefix` (first 4 hex characters) is included for identification purposes.

---

### `POST /v1/keys/create`

Create a new API key.

**Authentication:** Clerk session (dashboard only).

#### Request Body

| Field         | Type     | Required | Description                              |
|---------------|----------|----------|------------------------------------------|
| `environment` | `string` | Yes      | `live` or `test`.                        |
| `label`       | `string` | No       | Human-readable label for the key.        |

#### Response `201 Created`

```json
{
  "key_id": "key_01HXZ...",
  "api_key": "psc_live_a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6",
  "created_at": "2026-03-31T19:00:00Z"
}
```

**The `api_key` field is shown exactly once in this response.** It is not stored on the server and cannot be retrieved again. Clients must copy and store it securely.

---

### `POST /v1/keys/revoke`

Revoke an existing API key. Revocation is permanent and immediate.

**Authentication:** Clerk session (dashboard only).

#### Request Body

| Field    | Type     | Required | Description                  |
|----------|----------|----------|------------------------------|
| `key_id` | `string` | Yes      | The ID of the key to revoke. |

#### Response `200 OK`

```json
{
  "key_id": "key_01HXY...",
  "revoked_at": "2026-03-31T19:05:00Z"
}
```

After revocation any request using this key will receive `401 Unauthorized`.

---

### `GET /v1/usage`

Returns usage data for the current billing period.

**Authentication:** Bearer API key or Clerk session.

#### Response `200 OK`

```json
{
  "period_start": "2026-03-01T00:00:00Z",
  "period_end": "2026-03-31T23:59:59Z",
  "peak_objects": 245,
  "peak_principals": 18,
  "current_objects": 230,
  "current_principals": 17,
  "current_scopes": 3,
  "audit_entries_synced": 12480
}
```

Peak values represent the high-water mark during the billing period and are used for metered billing calculations.

---

### `GET /v1/plan`

Returns the current plan and its limits.

**Authentication:** Bearer API key or Clerk session.

#### Response `200 OK`

```json
{
  "plan_id": "starter",
  "name": "Starter",
  "limits": {
    "max_objects": 500,
    "max_principals": 50,
    "audit_retention_days": 90,
    "min_sync_interval_seconds": 30
  },
  "overage_allowed": true,
  "price_cents_monthly": 2900
}
```

---

## Error Format

All error responses use a consistent JSON structure:

```json
{
  "error": "error_code",
  "message": "Human-readable description of the error.",
  "details": {}
}
```

| Status | Error Code            | Description                                           |
|--------|-----------------------|-------------------------------------------------------|
| `400`  | `validation_error`    | Request body failed validation.                       |
| `401`  | `authentication_error`| Missing, invalid, or revoked API key.                 |
| `402`  | `plan_limit_exceeded` | Resource usage exceeds plan limits (free tier).        |
| `404`  | `not_found`           | Requested resource does not exist.                    |
| `429`  | `sync_interval`       | Batch submitted before minimum sync interval elapsed. |

The `details` object contains error-specific context. For validation errors it includes a mapping of field names to error messages. For plan limit errors it includes the current counts and the plan limits.
