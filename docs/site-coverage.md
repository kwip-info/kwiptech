# Site Coverage Plan

Phased build order for the full pyscoped platform surface. Each phase builds on the previous — later phases assume earlier ones are live.

## Phase 1 — Foundation (Public + Auth + Core Dashboard)

Get the marketing site live, auth working, and a minimal authenticated dashboard that proves the sync loop end-to-end.

| Section | Page | Notes |
|---------|------|-------|
| Public | Landing page | Value prop, CTA to sign up |
| Public | Pricing | Usage-based calculator (objects, principals, retention, sync frequency) |
| Public | Status page | System health, incident history |
| Public | Security / Trust | Data residency guarantees, encryption, compliance posture |
| Legal | Terms of Service | |
| Legal | Privacy Policy | |
| Legal | Cookie Policy | |
| Auth | Sign up / Register | |
| Auth | Login | |
| Auth | Forgot password / Reset | |
| Auth | Email verification | |
| Auth | Logout | |
| Onboarding | Welcome wizard | Create first key → install SDK → verify first sync |
| Dashboard | Overview | Health-at-a-glance: sync status, resource counts, recent activity |

## Phase 2 — Core Product (Keys + Sync + Audit)

The three things customers interact with daily. This is the "why pay for the management plane" phase.

| Section | Page | Notes |
|---------|------|-------|
| API Keys | Key list | Live vs test, active vs revoked |
| API Keys | Create key | Label, environment selection; full key shown once |
| API Keys | Key detail | Usage stats, last used, created by |
| API Keys | Revoke / Rotate | Confirmation flow, grace period options |
| Sync Agent | Agent status | Connected/disconnected, last sync, current state |
| Sync Agent | Sync history | Batch log with sequence ranges, entry counts, chain hashes |
| Sync Agent | Chain verification | Integrity check results, mismatch alerts |
| Sync Agent | Setup guide | Agent configuration, troubleshooting |
| Audit Trail | Search & browse | Filter by actor, action, target type, time range, scope |
| Audit Trail | Entry detail | Single entry with chain context (previous/next) |
| Audit Trail | Export | CSV/JSON for compliance handoff |
| Dashboard | Activity feed | Real-time stream of synced audit events |

## Phase 3 — Billing + Usage

Turn the product into a business. Usage tracking, payment, invoices.

| Section | Page | Notes |
|---------|------|-------|
| Usage | Usage dashboard | Current period: objects, principals, scopes (current vs peak) |
| Usage | Usage history | Trends over time, charts |
| Billing | Plan management | Current plan, upgrade/downgrade |
| Billing | Payment methods | Card on file, billing email |
| Billing | Invoices | History, downloadable PDFs |
| Billing | Billing alerts | Threshold configuration, approaching-limit notifications |

## Phase 4 — Teams + Organization

Multi-user support. Orgs, roles, team audit trail.

| Section | Page | Notes |
|---------|------|-------|
| Org | Org settings | Name, logo, default environment |
| Org | Team members | Invite, remove, role assignment |
| Org | Roles & permissions | Key admin vs view-only vs billing admin |
| Org | Platform audit log | Who on the team did what in the management plane (dogfooding) |
| Auth | Invite accept | Team member joining an org |
| Auth | MFA / 2FA setup | Setup, recovery codes |
| Account | Profile settings | Name, email, avatar |
| Account | Notification preferences | Email digests, sync failure alerts, billing alerts |
| Account | Security settings | Password change, MFA, active sessions |

## Phase 5 — Reports + Compliance

The features that justify enterprise pricing. Generated reports, compliance evidence.

| Section | Page | Notes |
|---------|------|-------|
| Reports | Object activity | Creates, updates, tombstones over time |
| Reports | Principal activity | Most active actors, access patterns |
| Reports | Scope utilization | Sharing patterns, membership |
| Compliance | Compliance reports | SOC 2 evidence, access reviews |
| Legal | Data Processing Agreement (DPA) | Enterprise requirement |
| Legal | SLA | Uptime guarantees, support tiers |
| Legal | Acceptable Use Policy | |

## Phase 6 — Developer Tools + Integrations

Power-user features. Webhooks, sandbox UX, API docs.

| Section | Page | Notes |
|---------|------|-------|
| Developer | API reference | Interactive docs for the management plane API |
| Developer | Webhooks | Outbound webhooks for sync events, billing, key lifecycle |
| Developer | SDK compatibility | Version checker, migration guides |
| Developer | Sandbox / test mode | First-class live/test toggle in dashboard UX |
| Public | Docs portal | SDK quickstart, API reference, guides, changelog |
| Public | Blog | |
| Public | About / Team | |
| Public | Contact / Support | Contact form, support channels |

## Phase 7 — Enterprise + Scale

SSO, advanced security, key scoping. Gate these behind enterprise plans.

| Section | Page | Notes |
|---------|------|-------|
| Auth | SSO / SAML configuration | Enterprise identity provider integration |
| API Keys | Key permissions / scoping | Restrict keys to specific operations |
| Account | API access tokens | Personal tokens vs org-level keys |

## Utility Pages (Build alongside Phase 1)

| Page | Notes |
|------|-------|
| 404 Not Found | |
| 403 Forbidden | |
| 500 Server Error | |
| 503 Maintenance mode | |
| 429 Rate limit exceeded | |
| Account suspended | Billing overdue state |
