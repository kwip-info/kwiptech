# Synthetic browser UAT

Use only a dedicated loopback PostgreSQL database. This workflow does not download data,
contact Stripe, or authenticate real Clerk accounts. Its RSA-signed session fixtures still
exercise the production JWT verification and scoped API paths. Never deploy `uat.settings`.

The checked-in settings deliberately fix the database to `market_uat` on
`127.0.0.1:55439`, PostgreSQL user `postgres`, local fixture password
`catalog-local-only`. Create that isolated database before starting. Production's
`DATABASE_URL` is ignored. Bind the server only to loopback.

```sh
KWIP_UAT=1 python manage.py migrate --settings=uat.settings
KWIP_UAT=1 python manage.py shell --settings=uat.settings -c 'import uat.seed'
KWIP_UAT=1 python manage.py runserver 127.0.0.1:8043 --settings=uat.settings --noreload
KWIP_UAT=1 python manage.py run_marketplace_worker --settings=uat.settings
```

The seed creates 63 invented job postings and Free, Pro, operator workspaces. It is
repeatable and displays a synthetic banner. Sign out to choose another fixture account.
All fixture tokens and rows belong only to this local environment. UAT routes are not
part of the production URL configuration. Remove the isolated database after testing.

## Browser acceptance scenarios

1. Browse/search catalog; inspect schema/evidence without credits; verify missing/search-empty states.
2. Retrieve page, filter, next page; compare visible price/receipt with the account ledger.
3. Check empty results cost zero. Retry a lost response with original request ID; exactly one debit.
4. Create, copy/hide and revoke a key; a revoked key cannot retrieve records or cached receipts.
5. Start device approval from API; review name/scopes, approve or deny; polling is rate-bounded and one-shot.
6. Pro prepares JSONL/CSV export with explicit budget; worker completes; download repeats free.
7. Set a small export budget; partial results are clearly marked and totals match prepared records.
8. Signed-out paths offer sign-in; Free cannot export; service keys cannot change account/billing.
9. Empty catalog disables purchases. Real Stripe sandbox separately tests Checkout, webhooks, portal,
   overage reconciliation, cancellation, network ambiguity, and out-of-order delivery.
10. Desktop and390px viewport: navigation, keyboard labels/focus, table horizontal scrolling,
    forms and failure messages remain usable. Recheck old product/document redirects and v1 410s.

Synthetic tests do not substitute for provider-connected UAT. Deployment evidence records those
separately. No real customer charge or external dataset collection is part of acceptance testing.
