---
title: Dashboard Guide
description: Comprehensive guide to the pyscoped platform dashboard, covering usage monitoring, API key management, audit trail, billing, roles, and application configuration.
category: Platform Usage
---

# Dashboard Guide

The pyscoped dashboard is the web interface for managing your organization's resources, monitoring SDK activity, and configuring access control. It is built with Django templates, Tailwind CSS, HTMX, and Alpine.js.

---

## Overview Page

The overview page (`/dashboard/`) is the landing page after sign-in. It provides a high-level summary of your organization's current state.

All data on the overview page is filtered by the active application and environment selected via the header toggles. The subtitle shows the current context (e.g., "Default · Test").

### Summary Cards

Four cards at the top:

- **API Keys** — Active key count for the selected app + environment. Links to key management.
- **Sync Status** — Last sync time, or "No data" if no sync agent connected.
- **Active Objects** — Current object and principal counts from the latest `UsageSnapshot`.
- **Audit Activity** — Number of synced audit entries received today. Links to the audit trail.

### Activity Feed + Key Status

Two-column layout:

- **Recent Activity** — The 10 most recent synced audit entries for the current app+env, showing action badge, target type, target ID, and relative timestamp.
- **Key Status** — Donut chart showing active vs. revoked keys for the selected environment.

### Charts

- **SDK Activity (7 days)** — Bar chart of daily synced operation counts from `SyncedAuditEntry`.
- **Resource Trends (30 days)** — Area chart of objects, principals, and scopes from `UsageSnapshot`.
- **Audit Volume (30 days)** — Bar chart of daily synced entry counts.

All charts are filtered by the active app + environment and labeled with the current context.

---

## API Key Management

Access from the sidebar: **Settings > API Keys** (`/dashboard/keys/`).

### Key List

A paginated table of all API keys in the current application:

| Column       | Description                                          |
|--------------|------------------------------------------------------|
| Prefix       | First segment of the key (e.g. `psc_live_a1b2`).    |
| Label        | Optional human-readable label.                       |
| Environment  | `live` or `test` badge.                              |
| Status       | `Active` (green) or `Revoked` (red).                 |
| Created      | Relative timestamp (e.g. "3 days ago").              |
| Last Used    | Relative timestamp or "Never".                       |

**Filtering:**
- Environment dropdown: All, Live, Test.
- Toggle: Show/hide revoked keys.

### Create Key

Click **Create Key** to open a modal dialog:

1. Select the environment (`live` or `test`).
2. Optionally enter a label (e.g. "Production Backend", "CI Pipeline").
3. Click **Create**.

The modal displays the full API key exactly once with a copy-to-clipboard button and a warning:

> This is the only time the full key will be shown. Copy it now and store it securely. You will not be able to retrieve it again.

The key is transmitted over HTTPS and never logged server-side. Only the SHA-256 hash is persisted.

### Key Detail

Click any key row to navigate to the detail page (`/dashboard/keys/<key_id>/`):

- **Metadata**: key ID, prefix, environment, label, creation date, creator account.
- **Version History**: If the key was rotated, a timeline of previous versions with their active periods.
- **Audit Trail**: Filtered view of audit entries associated with this key (synced using this key's credentials).
- **Reveal Secret**: Not available. The raw key cannot be retrieved after creation.

### Revoke a Key

On the key detail page or via the list's action menu:

1. Click **Revoke**.
2. Confirm in the dialog: "Revoking this key is permanent. Any SDK instances using it will immediately lose the ability to sync."
3. The key is marked `is_active = False` and `revoked_at` is recorded.

Revocation takes effect immediately. There is no grace period.

### Rotate a Key

Rotation creates a new key with the same environment and label, then revokes the old key:

1. Click **Rotate** on the key detail page.
2. A new key is generated and displayed (same one-time-show behavior as creation).
3. The old key is revoked automatically.
4. The new key inherits the label and application association of the old key but has its own independent lifecycle and audit trail.

This allows zero-downtime credential rotation: deploy the new key to your SDK configuration, verify sync is working, and the old key is already revoked.

---

## Audit Trail Viewer

Access from the sidebar: **Audit Trail** (`/dashboard/audit/`).

A searchable, filterable log of `SyncedAuditEntry` records. Data is scoped to the active application and environment via the header toggles — entries are filtered by accounts whose API keys match the selected app + env.

### Filters

| Filter       | Type         | Description                                          |
|--------------|--------------|------------------------------------------------------|
| Search       | Text input   | Full-text search across action, target type, target ID, and actor ID. |
| Action       | Dropdown     | Dynamic — populated from distinct actions in the synced data.  |
| Target Type  | Dropdown     | Dynamic — populated from distinct target types in the synced data. |
| Since / Until| Date pickers | Filter by entry timestamp range.                     |

Filters are applied via form submission. The action and target type dropdowns are built dynamically from actual data in `SyncedAuditEntry` for the organization, so they always reflect what's present.

### Results Table

| Column       | Description                                 |
|--------------|---------------------------------------------|
| #            | Entry sequence number.                      |
| Action       | Color-coded badge (green=create, blue=update, red=delete/revoke, purple=membership, amber=access_check). |
| Target       | Target type + truncated target ID. Scope ID shown below when present. |
| Actor        | Actor ID, or "System" with dot indicator.   |
| Time         | Date + time in tabular-nums format.         |

### Sorting

A toggle button switches between "Newest first" (default, `-sequence`) and "Oldest first" (`sequence`). Sort state is preserved across pagination and filter changes.

### Pagination

Results are paginated at 25 entries per page. Numbered page links (current ± 2, plus first and last page) with `«` / `»` arrows. Total count displayed (e.g., "11 entries" or "3 entries matching filters").

---

## Sync Status

Access from the sidebar: **Sync** (`/dashboard/sync/`).

### Connection Health

A status indicator showing:

- **Last Sync**: Timestamp of the most recent accepted batch.
- **Batch Interval**: Average time between batches over the last 24 hours.
- **Chain Status**: "Verified" (green) or "Mismatch Detected" (red) based on the most recent `/v1/sync/verify` result.

### Batch History

A paginated table of `SyncBatchRecord` entries:

| Column         | Description                                      |
|----------------|--------------------------------------------------|
| Batch ID       | Truncated UUID.                                  |
| Sequences      | `first_sequence` - `last_sequence`.              |
| Entries        | Number of entries in the batch.                  |
| SDK Version    | Version of the pyscoped SDK.                     |
| Status         | Accepted (green) or Rejected (red).              |
| Received At    | Server timestamp.                                |

### Chain Integrity Checks

A manual **Verify Chain** button triggers a chain integrity comparison. Results are displayed inline:

- Entry count comparison (local vs. server).
- Chain hash comparison.
- First mismatch sequence (if any).

---

## Applications

Access from the sidebar: **Applications** (`/dashboard/apps/`).

### Application List

A card grid showing each application with its name, slug, key count, and creation date. The default application is marked with a badge.

### Create Application

1. Click **New Application**.
2. Enter a name. The slug is auto-generated from the name (e.g. "My Backend API" becomes `my-backend-api`).
3. Click **Create**.

The application is created in both the Django database and pyscoped (via `create_app_in_scoped`).

### Edit Application

Click **Edit** on an application card to rename it. The rename propagates to pyscoped via `update_app_in_scoped`. The slug is regenerated from the new name.

### Delete Application

Click **Delete** to archive an application. Archived applications are soft-deleted: they no longer appear in the list but their data (keys, audit entries) is retained. API keys belonging to the application are automatically revoked.

---

## Roles and Permissions

Access from the sidebar: **Settings > Roles** (`/dashboard/roles/`).

### Role List

A table of roles in the current organization:

| Column           | Description                                  |
|------------------|----------------------------------------------|
| Name             | Role name (e.g. "Owner", "Developer").       |
| Permissions      | Count of assigned permissions.               |
| Members          | Count of members with this role.             |
| Default          | Badge if this is the default role.           |

### Permission Editor

Click a role to open the permission editor. Permissions are grouped by category with checkbox toggles:

```
Keys
  [x] keys.create     Create API keys
  [x] keys.revoke     Revoke API keys
  [x] keys.list       List and view API keys

Billing
  [ ] billing.manage  Manage subscription and payment methods
  [x] billing.view    View billing information and usage

Audit
  [x] audit.view      View audit trail entries
  [ ] audit.export    Export audit trail data

Members
  [ ] members.invite  Invite new members
  [ ] members.remove  Remove members
  [x] members.list    List organization members
```

Changes are saved via HTMX on each checkbox toggle. The corresponding pyscoped rules are updated via `update_role_rules_in_scoped`.

---

## Members

Access from the sidebar: **Members** (`/dashboard/members/`).

Each member card shows:

- **Email** — from the linked Account (backfilled from Clerk JWT claims or Clerk API).
- **Org role** — the default role for the organization, labeled "org default".
- **App overrides** — any app+env scoped role overrides (see below).
- **Joined date**.

### App + Environment Role Overrides

Members can have different roles for specific application and environment combinations. For example, a Developer at the org level can be restricted to Viewer on the production app's live environment.

**Adding an override:** Users with `members.manage` permission see an "+ Add app override" button on each member card. The form lets you select an application, environment (Test / Live / All environments), and role.

**Resolution order:** The middleware resolves the effective role on every request:
1. Check for an exact `(app, env)` override
2. Check for an app-wide override (`env = NULL`)
3. Fall back to the org-level role

**Removing an override:** Click the X button on any override row. The member reverts to their org-level role for that context.

The app/env toggles in the header are hidden on the Members page since role management is org-level. The overrides themselves specify which app+env they apply to.

---

## Billing

Access from the sidebar: **Billing** (`/dashboard/billing/`).

### Overview

Displays the current plan, billing period, and usage:

- **Plan**: Current plan name and monthly price.
- **Period**: Start and end dates of the current billing cycle.
- **Usage vs. Limits**: Bar charts for objects, principals, and audit entries showing current usage against plan limits.
- **Estimated Invoice**: Projected cost for the current period, including base price and any overage charges.

### Upgrade

Click **Upgrade Plan** to start a Stripe Checkout session. The checkout flow:

1. User selects the target plan (Starter, Team, or Enterprise).
2. Redirect to Stripe Checkout for payment method collection.
3. On success, Stripe webhook updates the organization's `plan`, `stripe_subscription_id`, and `billing_status`.
4. Redirect back to the billing page with a success message.

### Customer Portal

Click **Manage Billing** to open the Stripe Customer Portal in a new tab. From the portal, users can:

- Update payment methods.
- View invoice history.
- Cancel or modify the subscription.
- Download invoices and receipts.

---

## Key Analytics

Access from the sidebar: **Analytics > Keys** (`/dashboard/analytics/keys/`).

### Lifecycle Stats

Summary cards:

- **Total Keys Created**: All-time count.
- **Active Keys**: Currently active keys.
- **Revoked Keys**: All-time revoked count.
- **Average Lifespan**: Mean time from creation to revocation for revoked keys.

### Recency Buckets

A bar chart grouping active keys by last usage:

- Used in the last hour.
- Used in the last 24 hours.
- Used in the last 7 days.
- Used in the last 30 days.
- Not used in 30+ days (candidates for rotation or revocation).

### Creation Trends

A stacked area chart showing key creation over time, split by environment (`live` vs. `test`). Useful for identifying onboarding spikes or test activity patterns.

### Filtering

All charts and stats can be filtered by application using a dropdown at the top of the page.

---

## Environment and Application Switching

The dashboard header contains two selectors:

1. **Organization Selector**: Switch between organizations (if the user is a member of multiple). Stored in a session cookie.
2. **Application Selector**: Switch between applications within the current organization. Stored in a cookie (`pyscoped_app_context`).

Switching context updates the cookie and reloads the current page with data scoped to the selected organization and application. All dashboard views respect these context cookies to filter displayed data.

```
[ Acme Corp v ]  [ Production App v ]  [ live | test ]
```

The environment toggle (live/test) filters API keys and audit trail entries by environment without a full page reload (HTMX-powered).
