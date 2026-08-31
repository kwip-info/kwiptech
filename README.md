# KWIP Technology platform

This repository is the production Django control plane and public site at `https://kwip.tech`. It
is the public and commercial surface for KWIP Technology, not a fourth KWIP division and not a
hosted customer-document processing service.

## Current product boundary

- **Digest** is the pilot-ready, self-hosted document extraction runtime. Customer documents stay
  inside the customer's environment; this platform distributes product information, documentation,
  pilot intake, licensing, and release access.
- **PyScoped** is the maintained Python isolation, authorization, audit, and rollback framework.
  The platform provides its management-plane surfaces without becoming the system of record for a
  customer's application objects.
- **PyScoped Rules (`pyrule`)** is the smaller framework-agnostic authorization core for roles,
  permissions, entitlements, conditional rules, and usage limits. Its package repository owns the
  implementation contract.

The public catalog is intentionally narrow. Product implementation truth lives in the independent
Digest, PyScoped, and PyScoped Rules repositories; this repository owns their shared public and
commercial presentation at `kwip.tech`.

## Production architecture

- Django application on Heroku with managed PostgreSQL;
- Clerk for customer identity and organizations;
- Stripe for platform billing;
- Cloudflare for the `kwip.tech` DNS and edge boundary;
- GitHub Actions for CI and the current deployment path.

External ownership, sign-in routes, and credential boundaries are maintained in the enterprise
workspace's `operations/SERVICE_REGISTER.md` and `operations/CONTROL_PLANES.md`. Do not commit
credentials or treat repository configuration examples as production state.

## Repository map

- `plane/` — Django application, API, identity, billing, dashboard, and public-site behavior;
- `templates/` and `static/` — public and authenticated interface;
- `docs/platform/` — platform architecture, deployment, API, dashboard, and Digest boundary;
- `docs/sales/` — approved sales enablement inputs;
- `.github/workflows/` — CI and deployment automation.

Preserve the production URL, authentication domains, billing integration, and deployment path
unless a migration has an explicit cutover and rollback plan in the enterprise operations record.
