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

### Usage Cards

Four summary cards display real-time resource counts:

- **Active Objects** -- Current count vs. plan limit with a progress bar. Color shifts from green to amber to red as usage approaches the limit.
- **Active Principals** -- Same format as objects.
- **Audit Entries Synced** -- Total entries synced during the current billing period.
- **Sync Status** -- Time since the last successful batch sync. Displays "Connected" (green) if within 2x the plan's sync interval, "Stale" (amber) if lagging, or "Disconnected" (red) if no sync in 24+ hours.

### Activity Feed

A chronological feed of the 20 most recent audit entries, rendered in a compact timeline format:

```
12:34:05  alice  object.create  Document  doc_abc123
12:33:58  bob    rule.update    Role      role_editor
12:33:41  alice  member.invite  User      user_xyz
```

Each entry links to the full audit trail with the relevant filters pre-applied.

### Environment Breakdown Chart

An ApexCharts donut chart showing the distribution of API keys and audit activity across `live` and `test` environments. Hover for exact counts.

### Resource Trends

A line chart showing object and principal counts over the last 30 days, plotted from `UsageSnapshot` records. Useful for identifying growth patterns and forecasting plan upgrades.

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

A searchable, filterable log of all `SyncedAuditEntry` records for the current organization.

### Filters

| Filter       | Type         | Description                                          |
|--------------|--------------|------------------------------------------------------|
| Action       | Dropdown     | Filter by action name (e.g. `object.create`, `rule.update`). |
| Target Type  | Dropdown     | Filter by resource type (e.g. `Document`, `Role`).   |
| Actor        | Text input   | Filter by actor ID (partial match supported).        |
| Date Range   | Date picker  | Start and end dates for the time window.             |

Filters are applied via HTMX partial page updates -- no full page reload required.

### Results Table

| Column       | Description                                 |
|--------------|---------------------------------------------|
| Sequence     | Entry sequence number.                      |
| Timestamp    | Server-side received timestamp.             |
| Actor        | The principal who performed the action.     |
| Action       | Action name with color-coded badge.         |
| Target       | `{target_type}/{target_id}` link.           |
| Scope        | Scope ID, if present.                       |

### Pagination

Results are paginated at 50 entries per page. Navigation controls appear at the bottom of the table. Total entry count is displayed in the header.

### Entry Detail

Clicking a row expands an inline detail panel showing:

- Full entry metadata (all fields from `SyncedAuditEntry`).
- Chain integrity: hash and previous hash values.
- Metadata JSON rendered as a formatted key-value table.
- Trace ID link (if `parent_trace_id` is set).

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

Access from the sidebar: **Settings > Members** (`/dashboard/members/`).

A table of organization members:

| Column     | Description                              |
|------------|------------------------------------------|
| Name/Email | Member's email (from Account).           |
| Role       | Dropdown to reassign roles.              |
| Joined     | Relative timestamp.                      |
| Actions    | Remove button (if the user has permission). |

Role changes are applied immediately and synced to both Clerk (organization membership role) and pyscoped (membership rules).

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
