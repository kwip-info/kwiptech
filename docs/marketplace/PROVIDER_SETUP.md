# Repeatable Stripe marketplace setup

`configure_marketplace_billing` prepares the **new** marketplace product, monthly fixed and
per-credit metered prices, sum meter and signed webhook. It does not enable sales, create customers,
subscriptions, invoices or Checkout sessions, modify old PyScoped products, transfer price lookup
keys, rotate webhook secrets, or change the account's Billing Portal configuration.

The default is an **offline dry run**. It prints concrete intended amounts, event names, origin and
mode without requesting credentials, calling Stripe or writing files. It does not claim existing
objects have been inspected. `--dry-run` is explicit shorthand for the default.

```sh
python manage.py configure_marketplace_billing --dry-run
```

After reviewing the intent, an operator can deliberately apply it to a Stripe sandbox first:

```sh
python manage.py configure_marketplace_billing --apply \
  --output /absolute/private/directory/kwip-stripe-test.json
```

The parent directory must already exist and the absolute output path must be outside every Git
repository. The command creates the file with permissions 0600; an existing file must be owned by
the current user, regular, exactly 0600 and have no hard links. Symlinks and repository paths are
rejected. Keep the directory private too. The output is a **secret-bearing checkpoint/config file**,
not a release artifact: do not print it, attach it to a task, commit it, or put it in shared storage.
The CLI prints no Stripe API key, webhook secret or provider error body. Use a secure process to
install its `config` entries in the matching deployment's secret/config store.

## Required input and resulting objects

The command reads the existing server-owned settings through the Stripe gateway:

- `MARKET_STRIPE_SECRET_KEY`: matching test/live secret or appropriately restricted credential.
- `MARKET_STRIPE_LIVEMODE`: false for sandbox, true for separately authorized production setup.
- `MARKET_ORIGIN`: HTTPS origin without a path, query, fragment or embedded credentials.
- `MARKET_PRO_MONTHLY_CENTS`: default 2900; `MARKET_OVERAGE_CENTS_PER_10000`: default 100.
- `MARKET_STRIPE_METER_EVENT`: default `kwip_overage_credits`.

The credential needs permission to read current account identity and read/create products, prices,
billing meters and webhook endpoints. It does not need to create customers/subscriptions for this
command. Credential and configured mode must agree. Switching Stripe accounts, modes, amounts,
event names or webhook origins requires a different reviewed setup plan; an existing journal
cannot be silently repurposed. The command checks the provider account ID on each apply.

| Object | Identity / contract |
|---|---|
| Product | Deterministic `prod_kwip_marketplace_v1`, name `KWIP Data Marketplace`, marketplace ownership metadata. |
| Fixed price | Lookup key `kwip_marketplace_v1_pro_monthly_usd`; USD monthly licensed per-unit, configured integer cents. |
| Overage price | Lookup key `kwip_marketplace_v1_overage_monthly_usd`; USD monthly metered per-unit; configured cents divided by 10000 using Decimal. Default 100/10000 = 0.01 cents per excess credit. No included tier or quantity transform. |
| Meter | Configured event name, display name `KWIP Marketplace overage credits v1`, active sum aggregation; customer from payload `stripe_customer_id`, value from payload `value`; no event time window. |
| Webhook | `MARKET_ORIGIN/integrations/stripe`, account events, marketplace metadata, pinned API version `2026-02-25.clover`. No wildcard subscriptions. |

The event list matches the gateway's subscription reconciliation handler:
`checkout.session.completed`, `invoice.paid`, `invoice.payment_failed`,
`invoice.payment_action_required`, `customer.subscription.created`,
`customer.subscription.updated`, `customer.subscription.deleted`,
`customer.subscription.paused`, `customer.subscription.resumed`,
`customer.subscription.pending_update_applied`, and
`customer.subscription.pending_update_expired`.
These trigger a read of current provider subscription state; event arrival order is not entitlement
authority. Meter submission/validation failures still need the separate operational monitoring
procedure in BILLING_CONTRACT.md and OPERATIONS.md; this setup command does not invent handlers.

## Reuse, conflicts and partial failure

Apply discovers existing objects before creating anything. Product ID, price lookup keys, meter
event name and webhook URL/metadata identify candidates. Matching objects are validated, reused
and recorded. The command refuses conflicting amounts, mode, owners, meter mappings, inactive
objects, event lists or multiple matching endpoints. It never edits an incompatible object into
compliance or transfers a lookup key. Versioned price changes require a separate reviewed migration.
Discovery pagination is bounded at 1000 objects per list; incomplete/cyclic pagination stops instead
of assuming an object does not exist.

Create calls carry deterministic idempotency keys. The private output records account/intent and
checkpoints object IDs after each successful step. Re-run the **same command, settings and output**
after a transient failure. Provider lookup and validation are the durable deduplication mechanism;
Stripe's finite idempotency retention is an additional safeguard, not a permanent guarantee.
Only one setup process should run per Stripe account. A file lock prevents simultaneous writers to
the same journal; separate files/machines are not a distributed lock. Concurrent provisioning is
unsupported and must be resolved by looking up existing objects before retrying.

A crash can leave a partial journal or remote object whose response was lost. The command does not
roll back by deleting provider objects. Preserve the output and reconcile it against Stripe. The
file is flushed after checkpoints, but an interrupted write can still require manual recovery;
keep it in protected local storage and do not assume a failed command made no remote changes.

Webhook signing secrets are returned only at endpoint creation. The command saves a newly returned
secret immediately to the private file. If a matching endpoint already exists but its secret is not
in that journal, it **stops rather than creating a duplicate endpoint**. Recover the endpoint's secret
from Stripe Dashboard into a temporary local environment variable using a secure mechanism, then:

```sh
python manage.py configure_marketplace_billing --apply \
  --output /absolute/private/directory/kwip-stripe-test.json \
  --existing-webhook-secret-env KWIP_RECOVERED_WEBHOOK_SECRET
```

Pass the variable **name**, never the secret value, on the command line. The command reads the secret
without printing it. Unset the recovery variable afterward. A recovered secret cannot be proven to
match an endpoint solely through a Stripe read API; a signed delivery test remains required.
Do not substitute an unrelated historical PyScoped endpoint secret.

## Completion does not activate billing

Output status `configured_requires_uat` means objects were created/reused and a private configuration
was recorded. `ready_for_sales` remains false and `MARKET_BILLING_ENABLED` is false in the output.
The current application environment is not modified by this command.

Before any live activation, independently verify:

1. The matching deployment has the private price IDs, meter name and signing secret, correct mode,
   Clerk configuration, and an operating marketplace worker.
2. Real sandbox Checkout and Portal behavior; signed webhook delivery/replay; paid/unpaid/canceled
   entitlement; explicit overage opt-in/cap; meter event submission and reconciliation.
3. Provider account eligibility, published terms and tax treatment, plus a separately configured
   Billing Portal. Product/price creation is not merchant or tax readiness.
4. Approved production dataset rights and available data. This release must end empty and sales
   disabled; setup is not permission to seed data, subscribe a customer or perform a live charge.

The mocked tests exercise no network calls. They verify offline preview, explicit apply, private
output safeguards, identity/mode mismatch, unchanged/partial reruns, price/meter drift, duplicate
webhooks, create-only secret recovery and preserving unrelated products. They do not replace
provider sandbox UAT. Full billing/reconciliation behavior remains in BILLING_CONTRACT.md.

References: [create product](https://docs.stripe.com/api/products/create),
[create price](https://docs.stripe.com/api/prices/create),
[price lookup keys](https://docs.stripe.com/products-prices/manage-prices),
[create meter](https://docs.stripe.com/api/billing/meter/create),
[create webhook endpoint](https://docs.stripe.com/api/webhook_endpoints/create),
[idempotency](https://docs.stripe.com/api/idempotent_requests).
Implementation uses installed Stripe Python SDK 14.4.1 typed service methods and API version
`2026-02-25.clover`; verify compatibility before changing either.
