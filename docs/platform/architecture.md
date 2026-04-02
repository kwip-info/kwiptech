---
title: Platform Architecture
description: Technical architecture of the pyscoped platform, including the dual-model pattern, authentication flows, billing pipeline, middleware stack, and dogfooding strategy.
category: Platform Internals
---

# Platform Architecture

The pyscoped platform is the management plane for the pyscoped authorization library. It provides a SaaS dashboard for teams to manage API keys, monitor SDK activity, view audit trails, and handle billing. This document describes the technical architecture and design decisions.

---

## Tech Stack

| Layer          | Technology                          | Purpose                                      |
|----------------|-------------------------------------|----------------------------------------------|
| Backend        | Django 5+                           | Web framework, ORM, migrations, templates.   |
| API Layer      | Django REST Framework (DRF)         | REST API endpoints for SDK sync.             |
| Database       | PostgreSQL 16                       | Primary datastore for all models.            |
| Auth (UI)      | Clerk                               | User authentication, organization management.|
| Auth (SDK)     | API Keys (SHA-256)                  | SDK-to-platform authentication.              |
| Billing        | Stripe                              | Subscriptions, metered billing, checkout.    |
| CSS            | Tailwind CSS                        | Utility-first styling for dashboard UI.      |
| Interactivity  | HTMX                               | Server-driven partial page updates.          |
| Client State   | Alpine.js                           | Lightweight client-side reactivity.          |
| Charts         | ApexCharts                          | Usage charts and analytics visualizations.   |
| Static Files   | WhiteNoise                          | Compressed static file serving.              |

---

## Dual-Model Pattern

Every domain entity in the platform exists in two forms simultaneously:

1. **Django model** -- A PostgreSQL-backed record used for fast reads, dashboard rendering, filtering, and pagination. This is the projection layer.
2. **pyscoped object** -- An authoritative record in the pyscoped library's lifecycle-managed store. This is the source of truth for authorization state, versioning, and audit history.

The Django model stores a `scoped_*_id` field (e.g. `scoped_principal_id`, `scoped_scope_id`, `scoped_object_id`) that links it to its pyscoped counterpart.

### Why Both?

- **Django models** are optimized for relational queries: JOINs, aggregation, pagination, admin. They serve the dashboard UI and API responses efficiently.
- **pyscoped objects** provide lifecycle guarantees: immutable audit trails, hash-chained versioning, rule-based access control. They are the authoritative record for authorization decisions.

Writes always go through pyscoped first, then the Django model is updated as a projection. If the pyscoped write succeeds but the Django update fails, the system is eventually consistent -- the pyscoped state is canonical.

### Example Flow: Creating an Application

```python
# 1. Create in pyscoped (authoritative)
scoped_scope = scoped_client.scopes.create(
    name=application_name,
    parent_scope_id=organization.scoped_scope_id,
)

# 2. Create Django model (projection)
application = Application.objects.create(
    organization=organization,
    name=application_name,
    slug=slugify(application_name),
    scoped_scope_id=scoped_scope.id,
)
```

---

## Model-Level Scoped Sync

Each model that integrates with pyscoped has sync methods directly on the model class. This replaces the previous `scoped_sync.py` module (removed in v0.7.1).

### Sync Methods

| Model | Method | Description |
|---|---|---|
| `Organization` | `sync_to_scoped()` | Creates/updates pyscoped Principal (kind="org") + top-level Scope |
| `Organization` | `archive_in_scoped()` | Archives the org's pyscoped Scope |
| `Application` | `sync_to_scoped()` | Creates/updates a child Scope under the org |
| `Application` | `archive_in_scoped()` | Archives the app's pyscoped Scope |
| `Membership` | `sync_to_scoped()` | Adds member to org scope via pyscoped ScopeMembership |
| `Membership` | `bulk_sync_to_scoped()` | Bulk-adds multiple members |
| `Membership` | `revoke_in_scoped()` | Revokes member from org scope |
| `Role` | `sync_rules_to_scoped()` | Archives old rules + creates ACCESS rules per permission |
| `Role` | `archive_rules_in_scoped()` | Archives all pyscoped rules for the role |

### Graceful Degradation

All sync methods are wrapped in try/except blocks. If pyscoped is unavailable, the platform logs a structured warning and continues. The Django model is always persisted first — pyscoped sync is additive.

```python
# Call sites are explicit — sync happens after Django persist
org = Organization.objects.create(id=uuid4().hex, name=name, slug=slug, owner=owner)
org.sync_to_scoped()  # Graceful — logs on failure, never blocks

# Updates
org.name = new_name
org.save(update_fields=["name"])
org.sync_to_scoped(updated_by=actor_id)

# Deletes
org.archive_in_scoped(archived_by=actor_id)
org.status = "archived"
org.save(update_fields=["status"])
```

This ensures that a pyscoped outage does not take down the platform. The dashboard remains functional with degraded authorization capabilities.

---

## Authentication Flow

The platform has two distinct authentication paths depending on the client.

### Dashboard Authentication (Clerk)

For browser-based users accessing the dashboard:

```
Browser --> Clerk.js --> Clerk Backend --> JWT
  |
  v
Django Request
  |
  v
ClerkAuthMiddleware
  |-- Extracts JWT from session cookie
  |-- Verifies signature against Clerk JWKS
  |-- Extracts user_id and org_id from claims
  |-- Looks up or creates Account record (by clerk_user_id)
  |-- Looks up Organization and Membership
  |-- Sets request.user, request.organization, request.membership
  |
  v
ScopedContextMiddleware
  |-- Resolves pyscoped principal from request.organization.scoped_principal_id
  |-- Constructs ScopedContext with principal and scope
  |-- Attaches to request.scoped_context
  |
  v
View (access control via request.scoped_context)
```

### SDK Authentication (API Keys)

For programmatic access from the pyscoped SDK:

```
SDK --> POST /v1/sync/batch
        Authorization: Bearer psc_live_a1b2c3...
  |
  v
DRF Authentication Class (ApiKeyAuthentication)
  |-- Extracts token from Authorization header
  |-- Computes SHA-256 hash of the token
  |-- Looks up ApiKey record by key_hash
  |-- Verifies is_active = True
  |-- Updates last_used_at
  |-- Returns (account, api_key) as the DRF auth tuple
  |
  v
View (DRF permission classes check api_key.application, etc.)
```

The `ApiKeyAuthentication` class is a custom DRF authentication backend:

```python
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

class ApiKeyAuthentication(BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request):
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith(f"{self.keyword} "):
            return None

        raw_key = auth_header[len(self.keyword) + 1:]
        if not raw_key.startswith("psc_"):
            return None

        key_hash = ApiKey.hash_key(raw_key)
        try:
            api_key = ApiKey.objects.select_related(
                "account", "application"
            ).get(key_hash=key_hash, is_active=True)
        except ApiKey.DoesNotExist:
            raise AuthenticationFailed("Invalid or revoked API key.")

        api_key.last_used_at = timezone.now()
        api_key.save(update_fields=["last_used_at"])

        return (api_key.account, api_key)
```

---

## Principal Resolution

Both authentication paths resolve a pyscoped principal for use in `ScopedContext`. The resolution logic differs by path:

| Path      | Principal Source                                          |
|-----------|-----------------------------------------------------------|
| Dashboard | `request.organization.scoped_principal_id` (org-level)    |
| SDK       | The account associated with the API key, resolved via the key's application's organization |

The `ScopedContextMiddleware` constructs the context:

```python
class ScopedContextMiddleware:
    def __call__(self, request):
        if hasattr(request, "organization") and request.organization:
            principal_id = request.organization.scoped_principal_id
            scope_id = request.organization.scoped_scope_id
            if principal_id and scope_id:
                request.scoped_context = ScopedContext(
                    principal_id=principal_id,
                    scope_id=scope_id,
                )
            else:
                request.scoped_context = None
        else:
            request.scoped_context = None

        return self.get_response(request)
```

Views that require access control check `request.scoped_context` before performing operations:

```python
def create_application(request):
    if not request.scoped_context:
        return HttpResponseForbidden()

    if not request.scoped_context.has_permission("apps.create"):
        return HttpResponseForbidden("Insufficient permissions.")

    # proceed with creation...
```

---

## Billing Flow

The billing pipeline connects SDK activity to Stripe metered billing:

```
SDK Agent               Platform                    Stripe
   |                       |                          |
   |-- sync/batch -------->|                          |
   |                       |-- validate batch         |
   |                       |-- store SyncedAuditEntry |
   |                       |-- create UsageSnapshot   |
   |                       |-- update BillingPeriod   |
   |                       |   (peak tracking)        |
   |                       |                          |
   |                       |  [end of billing period] |
   |                       |-- finalize period        |
   |                       |-- calculate overages     |
   |                       |-- report usage --------->|
   |                       |                          |-- create invoice
   |                       |                          |-- charge customer
   |                       |<-- webhook (paid) -------|
   |                       |-- update billing_status  |
```

### Step-by-Step

1. **Batch Ingest**: The SDK agent calls `POST /v1/sync/batch` with audit entries and resource counts.
2. **Usage Snapshot**: After accepting a batch, the platform creates a `UsageSnapshot` recording current `active_objects`, `active_principals`, `active_scopes`, and `audit_entries_synced`.
3. **Peak Tracking**: The platform updates the current `BillingPeriod` with peak values. If the new snapshot's `active_objects` exceeds `peak_objects`, the peak is updated. Same for principals.
4. **Period Closure**: At the end of a billing period (triggered by a scheduled task or Stripe webhook), the platform finalizes the `BillingPeriod` and calculates overages.
5. **Stripe Reporting**: Overage quantities are reported to Stripe as metered usage items on the subscription.
6. **Invoicing**: Stripe generates an invoice combining the base subscription price with metered overage charges.

### Free Tier

Free tier organizations have hard limits. When `resource_counts` in a sync batch exceed `max_objects` or `max_principals`, the batch is rejected with `402`. No overage billing applies.

### Paid Tiers

Paid tier organizations have soft limits. Batches are always accepted (resource counts are tracked but not enforced at ingest time). Overages are calculated at period end and billed through Stripe.

---

## Middleware Stack

The full middleware stack in order:

```python
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",        # 1
    "whitenoise.middleware.WhiteNoiseMiddleware",            # 2
    "django.contrib.sessions.middleware.SessionMiddleware",  # 3
    "django.middleware.common.CommonMiddleware",             # 4
    "django.middleware.csrf.CsrfViewMiddleware",             # 5
    "django.contrib.auth.middleware.AuthenticationMiddleware",  # 6
    "core.middleware.ClerkAuthMiddleware",                   # 7
    "django.contrib.messages.middleware.MessageMiddleware",  # 8
    "django.middleware.clickjacking.XFrameOptionsMiddleware",  # 9
    "core.middleware.ScopedContextMiddleware",               # 10
]
```

| Position | Middleware                  | Purpose                                                   |
|----------|-----------------------------|-----------------------------------------------------------|
| 1        | `SecurityMiddleware`        | HTTPS redirect, HSTS, content type sniffing protection.   |
| 2        | `WhiteNoiseMiddleware`      | Serves static files with compression and cache headers. Must be early to short-circuit static requests. |
| 3        | `SessionMiddleware`         | Loads/saves session data. Required before auth middleware. |
| 4        | `CommonMiddleware`          | URL normalization (trailing slashes, `APPEND_SLASH`).     |
| 5        | `CsrfViewMiddleware`       | CSRF token validation. Must run before views process forms.|
| 6        | `AuthenticationMiddleware`  | Attaches `request.user` from the Django session backend.  |
| 7        | `ClerkAuthMiddleware`       | Verifies Clerk JWT, syncs user/org, enriches request.     |
| 8        | `MessageMiddleware`         | Django messages framework for flash notifications.        |
| 9        | `XFrameOptionsMiddleware`   | Prevents clickjacking by setting `X-Frame-Options`.       |
| 10       | `ScopedContextMiddleware`   | Resolves pyscoped principal/scope and attaches `ScopedContext`. Must be last -- depends on resolved user and org. |

---

## Dogfooding

The pyscoped platform uses the pyscoped library for its own operations. This serves two purposes: validating the library in a real production environment, and providing the platform itself with authorization, audit, and versioning capabilities.

### Audit Logging

All platform operations that modify state are logged through pyscoped's structured logging:

```python
from scoped.logging import scoped_logger

logger = scoped_logger(__name__)

def create_api_key(request, application):
    raw_key = ApiKey.generate_key(environment)
    api_key = ApiKey.objects.create(...)

    logger.info(
        "api_key.created",
        actor_id=str(request.user.id),
        target_type="ApiKey",
        target_id=str(api_key.id),
        scope_id=str(application.scoped_scope_id),
        metadata={
            "environment": environment,
            "application_id": str(application.id),
        },
    )
```

The structured log entries are captured by pyscoped's audit chain and synced back to the platform -- the platform audits itself.

### Rule-Based Access Control

Dashboard permission checks use pyscoped rules. When a role's permissions are modified in the dashboard, the corresponding pyscoped rules are updated via `update_role_rules_in_scoped`:

```python
# Role permissions synced via model method
role.sync_rules_to_scoped(created_by=actor_id)
# Archives old rules, creates fresh ACCESS rules per permission,
# bound to the org's pyscoped scope.
```

### Secrets Vault

API keys are registered in pyscoped's secrets vault as managed objects. This provides:

- Version tracking for key rotations.
- Audit trail of key lifecycle events (creation, use, revocation).
- Access control checks -- only principals with the `keys.create` or `keys.revoke` permissions can manage keys through the vault.

```python
def create_key_in_scoped(api_key):
    """Register an API key in pyscoped's secrets vault."""
    try:
        scoped_object = scoped_client.objects.create(
            object_type="api_key",
            scope_id=api_key.application.scoped_scope_id,
            metadata={
                "key_prefix": api_key.key_prefix,
                "environment": api_key.environment,
                "label": api_key.label or "",
            },
        )
        api_key.scoped_object_id = scoped_object.id
        api_key.save(update_fields=["scoped_object_id"])
    except Exception:
        logger.exception(
            "scoped_sync.key_create_failed",
            api_key_id=str(api_key.id),
        )
```

### Summary of Dogfooding Touchpoints

| Feature             | pyscoped Usage                                         |
|---------------------|--------------------------------------------------------|
| Audit logging       | `scoped.logging` for structured event capture.         |
| Access control      | `ScopedContext.has_permission()` for permission checks.|
| Role management     | pyscoped rules backing Django Role permissions.        |
| Key lifecycle       | Secrets vault for API key objects.                     |
| Org/App management  | pyscoped principals and scopes for org hierarchy.      |
| Membership          | pyscoped memberships linking principals to scopes.     |
| Versioning          | Hash-chained audit entries for all state mutations.    |
