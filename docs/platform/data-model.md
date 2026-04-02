---
title: Data Model Reference
description: Complete reference for all Django models in the pyscoped platform, including fields, constraints, indexes, and entity relationships.
category: Platform Internals
---

# Data Model Reference

All models live in the `core` Django app. Primary keys are UUIDs unless otherwise noted.

---

## Account

Represents an authenticated user. Created automatically on first Clerk sign-in via webhook or middleware sync.

| Field           | Type         | Constraints       | Description                                |
|-----------------|--------------|-------------------|--------------------------------------------|
| `id`            | `UUIDField`  | PK                | Auto-generated UUID.                       |
| `email`         | `EmailField` | Unique            | Email address from Clerk.                  |
| `clerk_user_id` | `CharField`  | Unique            | Clerk user identifier (`user_...`).        |
| `status`        | `CharField`  | Default `active`  | Account status: `active`, `suspended`.     |
| `created_at`    | `DateTimeField` | Auto             | Timestamp of account creation.             |

---

## Organization

A billable entity that owns applications, keys, roles, and members. Can be a personal organization (single user) or a shared team.

| Field                      | Type           | Constraints               | Description                                          |
|----------------------------|----------------|---------------------------|------------------------------------------------------|
| `id`                       | `UUIDField`    | PK                        | Auto-generated UUID.                                 |
| `name`                     | `CharField`    | Max 255                   | Display name.                                        |
| `slug`                     | `SlugField`    | Unique                    | URL-safe identifier.                                 |
| `clerk_org_id`             | `CharField`    | Unique, nullable          | Clerk organization ID (`org_...`). Null for personal orgs. |
| `is_personal`              | `BooleanField` | Default `False`           | True if this is a single-user personal organization. |
| `owner`                    | `ForeignKey`   | -> Account                | The account that owns this organization.             |
| `plan`                     | `ForeignKey`   | -> Plan                   | Current billing plan.                                |
| `stripe_customer_id`       | `CharField`    | Nullable                  | Stripe Customer ID (`cus_...`).                      |
| `stripe_subscription_id`   | `CharField`    | Nullable                  | Stripe Subscription ID (`sub_...`).                  |
| `billing_status`           | `CharField`    | Default `active`          | `active`, `past_due`, `canceled`, `trialing`.        |
| `scoped_principal_id`      | `CharField`    | Nullable                  | The pyscoped principal representing this org.        |
| `scoped_scope_id`          | `CharField`    | Nullable                  | The pyscoped scope for this org's resources.         |
| `status`                   | `CharField`    | Default `active`          | `active`, `suspended`, `archived`.                   |
| `created_at`               | `DateTimeField`| Auto                      | Timestamp of creation.                               |

---

## Application

A logical grouping of API keys and usage within an organization. Every organization has a default application created automatically.

| Field             | Type           | Constraints                        | Description                                    |
|-------------------|----------------|------------------------------------|-------------------------------------------------|
| `id`              | `UUIDField`    | PK                                 | Auto-generated UUID.                            |
| `organization`    | `ForeignKey`   | -> Organization                    | Parent organization.                            |
| `name`            | `CharField`    | Max 255                            | Display name.                                   |
| `slug`            | `SlugField`    | --                                 | URL-safe identifier, auto-generated from name.  |
| `scoped_scope_id` | `CharField`    | Nullable                           | The pyscoped scope for this application.        |
| `is_default`      | `BooleanField` | Default `False`                    | True for the auto-created default application.  |
| `created_at`      | `DateTimeField`| Auto                               | Timestamp of creation.                          |

**Constraints:**
- `unique_together: (organization, slug)` -- Slugs are unique within an organization.

---

## ApiKey

API credentials used by the SDK to authenticate with the sync endpoints.

| Field             | Type           | Constraints          | Description                                          |
|-------------------|----------------|----------------------|------------------------------------------------------|
| `id`              | `UUIDField`    | PK                   | Auto-generated UUID.                                 |
| `account`         | `ForeignKey`   | -> Account           | The account that created this key.                   |
| `application`     | `ForeignKey`   | -> Application       | The application this key belongs to.                 |
| `key_hash`        | `CharField`    | Unique, max 64       | SHA-256 hex digest of the full API key.              |
| `key_prefix`      | `CharField`    | Max 20               | First segment of the key for display (e.g. `psc_live_a1b2`). |
| `environment`     | `CharField`    | Choices: `live`, `test` | Environment this key is scoped to.                |
| `label`           | `CharField`    | Nullable, max 255    | Optional human-readable label.                       |
| `scoped_object_id`| `CharField`    | Nullable             | The pyscoped object representing this key.           |
| `is_active`       | `BooleanField` | Default `True`       | False after revocation.                              |
| `created_at`      | `DateTimeField`| Auto                 | Timestamp of creation.                               |
| `last_used_at`    | `DateTimeField`| Nullable             | Timestamp of most recent successful authentication.  |
| `revoked_at`      | `DateTimeField`| Nullable             | Timestamp of revocation, if revoked.                 |

**Static Methods:**

```python
@staticmethod
def generate_key(environment: str) -> str:
    """Generate a new API key string: psc_{env}_{64 hex chars}"""
    token = secrets.token_hex(32)
    return f"psc_{environment}_{token}"

@staticmethod
def hash_key(raw_key: str) -> str:
    """Return the SHA-256 hex digest of a raw API key."""
    return hashlib.sha256(raw_key.encode()).hexdigest()
```

---

## SyncedAuditEntry

An audit trail entry received from the SDK via batch sync. Entries form an immutable hash chain.

| Field             | Type           | Constraints                           | Description                                 |
|-------------------|----------------|---------------------------------------|---------------------------------------------|
| `id`              | `UUIDField`    | PK                                    | Auto-generated UUID.                        |
| `account`         | `ForeignKey`   | -> Account                            | The account that owns this entry.           |
| `sequence`        | `BigIntegerField` | --                                 | Monotonically increasing sequence number.   |
| `actor_id`        | `CharField`    | Max 255                               | Identifier of the acting principal.         |
| `action`          | `CharField`    | Max 255                               | Action name (e.g. `object.create`).         |
| `target_type`     | `CharField`    | Max 255                               | Resource type of the target.                |
| `target_id`       | `CharField`    | Max 255                               | Identifier of the target resource.          |
| `timestamp`       | `DateTimeField`| --                                    | Timestamp from the SDK.                     |
| `hash`            | `CharField`    | Max 64                                | SHA-256 hash of this entry.                 |
| `previous_hash`   | `CharField`    | Max 64                                | Hash of the preceding entry (chain link).   |
| `scope_id`        | `CharField`    | Max 255, nullable                     | Scope under which the action occurred.      |
| `parent_trace_id` | `CharField`    | Max 255, nullable                     | Trace ID for distributed tracing.           |
| `metadata_json`   | `JSONField`    | Default `{}`                          | Arbitrary key-value metadata.               |
| `batch_id`        | `UUIDField`    | --                                    | Reference to the ingesting SyncBatchRecord. |
| `received_at`     | `DateTimeField`| Auto                                  | Server-side timestamp of receipt.           |

**Indexes:**

| Index                                    | Type   | Purpose                                     |
|------------------------------------------|--------|----------------------------------------------|
| `(account, sequence)`                    | Unique | Fast chain traversal and dedup.              |
| `(account, actor_id)`                    | Index  | Filter audit trail by actor.                 |
| `(account, target_type, target_id)`      | Index  | Filter audit trail by target resource.       |
| `(account, timestamp)`                   | Index  | Time-range queries on audit trail.           |

---

## SyncBatchRecord

Metadata about each batch of audit entries received from the SDK.

| Field            | Type              | Constraints     | Description                                          |
|------------------|-------------------|-----------------|------------------------------------------------------|
| `id`             | `UUIDField`       | PK              | Auto-generated UUID.                                 |
| `account`        | `ForeignKey`      | -> Account      | The account that sent this batch.                    |
| `first_sequence` | `BigIntegerField` | --              | Sequence number of the first entry in the batch.     |
| `last_sequence`  | `BigIntegerField` | --              | Sequence number of the last entry in the batch.      |
| `chain_hash`     | `CharField`       | Max 64          | Rolling chain hash after the last entry.             |
| `content_hash`   | `CharField`       | Max 64          | SHA-256 hash of the serialized entries payload.      |
| `signature`      | `CharField`       | Max 128         | HMAC-SHA256 signature for integrity verification.    |
| `entry_count`    | `IntegerField`    | --              | Number of entries in this batch.                     |
| `sdk_version`    | `CharField`       | Max 20          | Version of the pyscoped SDK that produced the batch. |
| `received_at`    | `DateTimeField`   | Auto            | Server-side timestamp of receipt.                    |
| `accepted`       | `BooleanField`    | Default `True`  | False if the batch was rejected (validation, limits).|

---

## Permission

A static, seeded permission that can be assigned to roles. Permissions are defined in a data migration and are not user-editable.

| Field         | Type        | Constraints  | Description                                 |
|---------------|-------------|--------------|----------------------------------------------|
| `id`          | `UUIDField` | PK           | Auto-generated UUID.                         |
| `name`        | `CharField` | Unique       | Machine-readable name (e.g. `keys.create`).  |
| `category`    | `CharField` | Max 100      | Grouping category (e.g. `keys`, `billing`).  |
| `description` | `TextField` | --           | Human-readable description of the permission.|

---

## Role

A named set of permissions within an organization. Each organization can define custom roles. A default `Owner` role is created with all permissions for new organizations.

| Field             | Type           | Constraints                        | Description                                         |
|-------------------|----------------|------------------------------------|-----------------------------------------------------|
| `id`              | `UUIDField`    | PK                                 | Auto-generated UUID.                                |
| `organization`    | `ForeignKey`   | -> Organization                    | Parent organization.                                |
| `name`            | `CharField`    | Max 100                            | Role display name.                                  |
| `is_default`      | `BooleanField` | Default `False`                    | True for the auto-created Owner role.               |
| `permissions`     | `ManyToMany`   | -> Permission                      | Set of permissions granted by this role.             |
| `scoped_rule_ids` | `JSONField`    | Default `[]`                       | List of pyscoped rule IDs backing this role.         |
| `created_at`      | `DateTimeField`| Auto                               | Timestamp of creation.                              |

**Constraints:**
- `unique_together: (organization, name)` -- Role names are unique within an organization.

---

## Membership

Links an account to an organization with a specific role.

| Field                 | Type           | Constraints                         | Description                                       |
|-----------------------|----------------|-------------------------------------|---------------------------------------------------|
| `id`                  | `UUIDField`    | PK                                  | Auto-generated UUID.                              |
| `organization`        | `ForeignKey`   | -> Organization                     | The organization.                                 |
| `account`             | `ForeignKey`   | -> Account                          | The member account.                               |
| `role`                | `ForeignKey`   | -> Role                             | The role assigned to this member.                 |
| `clerk_membership_id` | `CharField`    | Nullable                            | Clerk organization membership ID.                 |
| `scoped_membership_id`| `CharField`    | Nullable                            | The pyscoped membership object.                   |
| `joined_at`           | `DateTimeField`| Auto                                | Timestamp when the account joined.                |

**Constraints:**
- `unique_together: (organization, account)` -- An account can only be a member of an organization once.

---

## Plan

Billing plan definitions. Plans are identified by tier name and define resource limits and pricing.

| Field                          | Type             | Constraints        | Description                                          |
|--------------------------------|------------------|--------------------|------------------------------------------------------|
| `id`                           | `CharField`      | PK, max 50         | Tier name (e.g. `free`, `starter`, `team`, `enterprise`). |
| `name`                         | `CharField`      | Max 100            | Display name.                                        |
| `max_objects`                  | `IntegerField`   | --                 | Maximum number of managed objects.                   |
| `max_principals`               | `IntegerField`   | --                 | Maximum number of principals.                        |
| `audit_retention_days`         | `IntegerField`   | --                 | Number of days audit entries are retained.            |
| `min_sync_interval_seconds`    | `IntegerField`   | --                 | Minimum seconds between sync batches.                |
| `price_cents_monthly`          | `IntegerField`   | --                 | Base monthly price in cents.                         |
| `stripe_monthly_price_id`      | `CharField`      | Nullable           | Stripe Price ID for monthly billing.                 |
| `stripe_annual_price_id`       | `CharField`      | Nullable           | Stripe Price ID for annual billing.                  |
| `included_objects`             | `IntegerField`   | Default 0          | Number of objects included before overage.           |
| `included_principals`          | `IntegerField`   | Default 0          | Number of principals included before overage.        |
| `included_audit_entries`       | `IntegerField`   | Default 0          | Audit entries included per billing period.           |
| `overage_rate_objects_cents`   | `IntegerField`   | Default 0          | Overage rate per object per month (in cents).        |
| `overage_rate_principals_cents`| `IntegerField`   | Default 0          | Overage rate per principal per month (in cents).     |
| `overage_rate_audit_cents`     | `IntegerField`   | Default 0          | Overage rate per 1,000 audit entries (in cents).     |
| `overage_allowed`              | `BooleanField`   | Default `False`    | Whether usage beyond limits is allowed (paid tiers). |

---

## UsageSnapshot

Point-in-time snapshot of resource usage, recorded after each successful batch sync.

| Field                  | Type           | Constraints    | Description                                     |
|------------------------|----------------|----------------|-------------------------------------------------|
| `id`                   | `UUIDField`    | PK             | Auto-generated UUID.                            |
| `account`              | `ForeignKey`   | -> Account     | The account.                                    |
| `organization`         | `ForeignKey`   | -> Organization| The organization.                               |
| `application`          | `ForeignKey`   | -> Application, nullable | The application (if scoped).           |
| `active_objects`       | `IntegerField` | --             | Current count of active objects.                |
| `active_principals`    | `IntegerField` | --             | Current count of active principals.             |
| `active_scopes`        | `IntegerField` | --             | Current count of active scopes.                 |
| `audit_entries_synced` | `IntegerField` | --             | Cumulative audit entries synced this period.     |
| `recorded_at`          | `DateTimeField`| Auto           | Timestamp of the snapshot.                      |

---

## BillingPeriod

Tracks usage aggregates over a billing cycle for metered billing.

| Field                 | Type              | Constraints     | Description                                         |
|-----------------------|-------------------|-----------------|-----------------------------------------------------|
| `id`                  | `UUIDField`       | PK              | Auto-generated UUID.                                |
| `account`             | `ForeignKey`      | -> Account      | The account.                                        |
| `organization`        | `ForeignKey`      | -> Organization | The organization.                                   |
| `period_start`        | `DateTimeField`   | --              | Start of the billing period.                        |
| `period_end`          | `DateTimeField`   | --              | End of the billing period.                          |
| `peak_objects`        | `IntegerField`    | Default 0       | High-water mark for active objects.                 |
| `peak_principals`     | `IntegerField`    | Default 0       | High-water mark for active principals.              |
| `total_audit_entries` | `IntegerField`    | Default 0       | Total audit entries synced during the period.        |
| `finalized`           | `BooleanField`    | Default `False` | True once the period has been closed and billed.    |

---

## Entity Relationship Diagram

```
                           +------------------+
                           |     Account      |
                           |------------------|
                           | id (PK)          |
                           | email            |
                           | clerk_user_id    |
                           | status           |
                           +--------+---------+
                                    |
                    +---------------+---------------+
                    | owns                          | member of
                    v                               v
          +---------+----------+          +---------+---------+
          |   Organization     |          |    Membership     |
          |--------------------|          |-------------------|
          | id (PK)            |          | id (PK)           |
          | name, slug         |<---------+ organization (FK) |
          | owner (FK Account) |          | account (FK)      |
          | plan (FK Plan)     |          | role (FK Role)    |
          | stripe_customer_id |          +-------------------+
          | billing_status     |                    |
          +----+-------+-------+                    v
               |       |                  +---------+---------+
               |       |                  |       Role        |
               |       |                  |-------------------|
               |       +----------------->| id (PK)           |
               |       has roles          | organization (FK) |
               |                          | name              |
               |                          | permissions (M2M) |
               |                          | scoped_rule_ids   |
               v                          +-------------------+
     +---------+----------+                         |
     |    Application     |                         v
     |--------------------|            +------------+---------+
     | id (PK)            |            |    Permission        |
     | organization (FK)  |            |----------------------|
     | name, slug         |            | id (PK)              |
     | is_default         |            | name                 |
     +----+---------------+            | category             |
          |                            | description          |
          | has keys                   +----------------------+
          v
     +----+---------------+        +----------------------+
     |      ApiKey        |        |        Plan          |
     |--------------------|        |----------------------|
     | id (PK)            |        | id (PK, tier name)   |
     | account (FK)       |        | name                 |
     | application (FK)   |        | max_objects           |
     | key_hash (unique)  |        | max_principals        |
     | environment        |        | audit_retention_days  |
     | is_active          |        | price_cents_monthly   |
     +--------------------+        | overage_allowed       |
                                   +----------------------+

     +-------------------------+   +-------------------------+
     |   SyncedAuditEntry      |   |   SyncBatchRecord       |
     |-------------------------|   |-------------------------|
     | id (PK)                 |   | id (PK)                 |
     | account (FK)            |   | account (FK)            |
     | sequence                |   | first_sequence          |
     | actor_id, action        |   | last_sequence           |
     | target_type, target_id  |   | chain_hash              |
     | hash, previous_hash     |   | content_hash            |
     | batch_id                |   | sdk_version             |
     | timestamp, received_at  |   | accepted                |
     +-------------------------+   +-------------------------+

     +-------------------------+   +-------------------------+
     |    UsageSnapshot        |   |    BillingPeriod        |
     |-------------------------|   |-------------------------|
     | id (PK)                 |   | id (PK)                 |
     | account (FK)            |   | account (FK)            |
     | organization (FK)       |   | organization (FK)       |
     | application (FK, null)  |   | period_start/end        |
     | active_objects           |   | peak_objects            |
     | active_principals        |   | peak_principals         |
     | audit_entries_synced     |   | total_audit_entries     |
     | recorded_at              |   | finalized               |
     +-------------------------+   +-------------------------+
```

**Key Relationships:**

- An **Account** owns many **Organizations** and holds many **Memberships**.
- An **Organization** contains many **Applications**, **Roles**, and **Memberships**.
- An **Application** has many **ApiKeys**.
- A **Role** has many **Permissions** (M2M) and belongs to one **Organization**.
- A **Membership** connects one **Account** to one **Organization** with one **Role**.
- **SyncedAuditEntry** and **SyncBatchRecord** are append-only tables linked to an **Account**.
- **UsageSnapshot** and **BillingPeriod** track metered usage per **Organization**.
