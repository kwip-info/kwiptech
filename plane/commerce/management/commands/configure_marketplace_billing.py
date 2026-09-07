"""Create only the new marketplace's provider configuration, with durable receipts."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from decimal import Decimal
from urllib.parse import urlsplit

import stripe
from django.core.management.base import BaseCommand, CommandError
from plane.access.errors import Problem
from plane.commerce.services import option
from plane.commerce.stripe_gateway import client

VERSION = '2026-02-25.clover'
PRODUCT_ID = 'prod_kwip_marketplace_v1'
OWNER = {'kwip_component': 'data_marketplace', 'kwip_setup_version': '1'}
EVENTS = sorted([
    'checkout.session.completed', 'invoice.paid', 'invoice.payment_failed',
    'invoice.payment_action_required', 'customer.subscription.created',
    'customer.subscription.updated', 'customer.subscription.deleted',
    'customer.subscription.paused', 'customer.subscription.resumed',
    'customer.subscription.pending_update_applied',
    'customer.subscription.pending_update_expired',
])


def intent():
    origin = option('ORIGIN', 'https://kwip.tech').rstrip('/')
    parsed = urlsplit(origin)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path:
        raise CommandError('MARKET_ORIGIN must be an HTTPS origin without credentials, path, query or fragment.')
    amount = option('PRO_MONTHLY_CENTS', 2900)
    overage = option('OVERAGE_CENTS_PER_10000', 100)
    if any(type(n) is not int or not 1 <= n <= 100000000 for n in (amount, overage)):
        raise CommandError('Configured monthly and overage amounts must be positive bounded integer cents.')
    event = option('STRIPE_METER_EVENT', 'kwip_overage_credits')
    if not isinstance(event, str) or not re.fullmatch(r'[A-Za-z0-9_]{1,100}', event):
        raise CommandError('MARKET_STRIPE_METER_EVENT must be a bounded identifier.')
    return {'api_version': VERSION, 'livemode': bool(option('STRIPE_LIVEMODE', False)),
            'product_id': PRODUCT_ID, 'monthly_cents': amount,
            'overage_unit_amount_decimal': str(Decimal(overage) / Decimal(10000)),
            'meter_event': event, 'webhook_url': origin + '/integrations/stripe',
            'events': EVENTS, 'currency': 'usd', 'billing_enabled': False}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def rows(service, params=None):
    """Bounded complete discovery; never mistake a partial list for absence."""
    params = dict(params or {}, limit=100)
    found, cursors = [], set()
    for _ in range(10):
        page = service.list(params=params)
        data = page.get('data', [])
        found.extend(data)
        if not page.get('has_more'):
            return found
        cursor = data[-1].get('id') if data else None
        if not cursor or cursor in cursors:
            raise CommandError('Provider pagination is incomplete; no absence can be inferred.')
        cursors.add(cursor)
        params = dict(params, starting_after=cursor)
    raise CommandError('Provider discovery exceeds 1000 objects; review manually before setup.')


def single(items, label):
    if len(items) > 1:
        raise CommandError(f'Multiple matching {label} objects exist; reconcile them without deleting or replacing objects.')
    return items[0] if items else None


def mode(obj, plan):
    if obj.get('livemode') is not plan['livemode']:
        raise CommandError('Existing provider object belongs to a different mode.')


def owned(obj):
    if any(obj.get('metadata', {}).get(k) != v for k, v in OWNER.items()):
        raise CommandError('Existing provider object is not owned by this marketplace setup; nothing will be overwritten.')


def validate_meter(meter, plan):
    mode(meter, plan)
    if (meter.get('event_name') != plan['meter_event'] or meter.get('display_name') != 'KWIP Marketplace overage credits v1'
            or meter.get('status') != 'active' or meter.get('default_aggregation', {}).get('formula') != 'sum'
            or meter.get('customer_mapping') != {'type': 'by_id', 'event_payload_key': 'stripe_customer_id'}
            or meter.get('value_settings') != {'event_payload_key': 'value'} or meter.get('event_time_window')):
        raise CommandError('Existing meter configuration differs. Do not silently adopt or change it.')


def validate_price(price, plan, product_id, meter_id, kind):
    mode(price, plan)
    owned(price)
    recurring = price.get('recurring') or {}
    expected_usage = 'licensed' if kind == 'pro' else 'metered'
    if (not price.get('active') or price.get('product') != product_id or price.get('currency') != 'usd'
            or price.get('billing_scheme') != 'per_unit' or recurring.get('interval') != 'month'
            or recurring.get('interval_count', 1) != 1 or recurring.get('usage_type') != expected_usage
            or price.get('transform_quantity') or price.get('tiers')):
        raise CommandError('Existing price configuration differs; use a reviewed versioned price migration.')
    if kind == 'pro':
        if price.get('unit_amount') != plan['monthly_cents']:
            raise CommandError('Existing fixed price differs; no lookup key will be transferred.')
    elif recurring.get('meter') != meter_id or str(price.get('unit_amount_decimal')) != plan['overage_unit_amount_decimal']:
        # Stripe can normalize trailing zeros, so compare exact decimals below.
        try:
            same = Decimal(str(price.get('unit_amount_decimal'))) == Decimal(plan['overage_unit_amount_decimal'])
        except Exception:
            same = False
        if recurring.get('meter') != meter_id or not same:
            raise CommandError('Existing metered price differs; no lookup key will be transferred.')


def validate_webhook(endpoint, plan):
    mode(endpoint, plan)
    owned(endpoint)
    if (endpoint.get('url') != plan['webhook_url'] or endpoint.get('status') != 'enabled'
            or endpoint.get('api_version') != VERSION or sorted(endpoint.get('enabled_events', [])) != EVENTS):
        raise CommandError('Existing webhook configuration differs; review manually, do not duplicate it.')


class Journal:
    """Private checkpoint file. Exclusive open/lock prevents symlinks and same-file races."""
    def __init__(self, filename):
        if not filename:
            raise CommandError('--apply requires --output with a private JSON path outside every Git repository.')
        raw = Path(filename).expanduser()
        if not raw.is_absolute():
            raise CommandError('--output must be an absolute path outside the repositories.')
        self.path = raw.parent.resolve() / raw.name
        if not self.path.parent.is_dir() or any((p / '.git').exists() for p in [self.path.parent, *self.path.parent.parents]):
            raise CommandError('--output must have an existing parent outside every Git repository.')
        self.fd = None
        try:
            try:
                self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            except FileExistsError:
                self.fd = os.open(self.path, os.O_RDWR | os.O_NOFOLLOW)
            meta = os.fstat(self.fd)
            if not stat.S_ISREG(meta.st_mode) or stat.S_IMODE(meta.st_mode) != 0o600 or meta.st_uid != os.getuid() or meta.st_nlink != 1 or meta.st_size > 65536:
                raise CommandError('Output must be a regular owner-only 0600 file, with no hard links and at most 64 KiB.')
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            raw_data = os.read(self.fd, 65537)
            self.data = json.loads(raw_data) if raw_data else {}
            if not isinstance(self.data, dict):
                raise CommandError('Output journal is not a JSON object.')
        except (OSError, ValueError, CommandError) as exc:
            self.close()
            if isinstance(exc, CommandError):
                raise
            raise CommandError('Cannot securely open/lock/read output journal; preserve it and review locally.') from None

    def save(self):
        payload = (json.dumps(self.data, indent=2, sort_keys=True) + '\n').encode()
        os.lseek(self.fd, 0, os.SEEK_SET)
        os.ftruncate(self.fd, 0)
        offset = 0
        while offset < len(payload):
            offset += os.write(self.fd, payload[offset:])
        os.fsync(self.fd)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


class Setup:
    def __init__(self, api, plan, journal, secret_env=None):
        self.api, self.plan, self.journal, self.secret_env = api, plan, journal, secret_env
        self.data = journal.data

    def remember(self, name, value):
        self.data.setdefault('objects', {})[name] = value
        self.journal.save()

    def create(self, service, params, label):
        key = 'kwip-marketplace-setup-v1-' + label + '-' + fingerprint(self.plan)[:24]
        return service.create(params, options={'idempotency_key': key})

    def run(self):
        account = self.api.v1.accounts.retrieve_current()
        account_id = account.get('id')
        if not isinstance(account_id, str) or not account_id.startswith('acct_'):
            raise CommandError('Provider account identity is unavailable.')
        identity = {'account_id': account_id, 'intent': self.plan}
        if self.data and self.data.get('identity') != identity:
            raise CommandError('Journal belongs to another account, mode or configuration; do not reuse it.')
        self.data.update(identity=identity, status='incomplete', ready_for_sales=False)
        self.journal.save()
        # Discover every reusable object before creating anything. Refuse conflicts first.
        try:
            product = self.api.v1.products.retrieve(PRODUCT_ID)
        except stripe.InvalidRequestError as exc:
            if exc.code != 'resource_missing' or exc.http_status != 404:
                raise
            product = None
        if product:
            mode(product, self.plan)
            owned(product)
            if not product.get('active') or product.get('name') != 'KWIP Data Marketplace':
                raise CommandError('Existing product differs; legacy products will not be changed.')
        meter = single([m for m in rows(self.api.v1.billing.meters) if m.get('event_name') == self.plan['meter_event']], 'meter')
        if meter:
            validate_meter(meter, self.plan)
        prices = {}
        for kind in ('pro', 'overage'):
            lookup = 'kwip_marketplace_v1_' + kind + '_monthly_usd'
            prices[kind] = single(rows(self.api.v1.prices, {'lookup_keys': [lookup]}), kind + ' price')
            if prices[kind]:
                if not product or (kind == 'overage' and not meter):
                    raise CommandError('Price exists without its expected product/meter; reconcile first.')
                validate_price(prices[kind], self.plan, PRODUCT_ID, meter['id'] if meter else None, kind)
        matching = [w for w in rows(self.api.v1.webhook_endpoints) if w.get('url') == self.plan['webhook_url']]
        webhook = single(matching, 'webhook')
        if webhook:
            validate_webhook(webhook, self.plan)
            known_id = self.data.get('objects', {}).get('webhook_id')
            saved_secret = self.data.get('config', {}).get('MARKET_STRIPE_WEBHOOK_SECRET') if known_id == webhook['id'] else None
            recovered = os.environ.get(self.secret_env, '') if self.secret_env else ''
            secret = saved_secret or recovered
            if not isinstance(secret, str) or not secret.startswith('whsec_'):
                self.remember('webhook_id', webhook['id'])
                raise CommandError('Existing webhook secret is not recoverable from Stripe API. Recover it in the Dashboard and rerun with --existing-webhook-secret-env NAME; never create a duplicate endpoint.')
        else:
            secret = None
        if not product:
            product = self.create(self.api.v1.products, {'id': PRODUCT_ID, 'name': 'KWIP Data Marketplace', 'metadata': OWNER}, 'product')
            mode(product, self.plan)
            owned(product)
        self.remember('product_id', product['id'])
        if not meter:
            meter = self.create(self.api.v1.billing.meters, {'display_name': 'KWIP Marketplace overage credits v1',
                'event_name': self.plan['meter_event'], 'default_aggregation': {'formula': 'sum'},
                'customer_mapping': {'type': 'by_id', 'event_payload_key': 'stripe_customer_id'},
                'value_settings': {'event_payload_key': 'value'}}, 'meter')
            validate_meter(meter, self.plan)
        self.remember('meter_id', meter['id'])
        for kind in ('pro', 'overage'):
            if not prices[kind]:
                params = {'product': product['id'], 'currency': 'usd', 'billing_scheme': 'per_unit', 'metadata': OWNER,
                          'lookup_key': 'kwip_marketplace_v1_' + kind + '_monthly_usd',
                          'recurring': {'interval': 'month', 'usage_type': 'licensed' if kind == 'pro' else 'metered'}}
                if kind == 'pro':
                    params['unit_amount'] = self.plan['monthly_cents']
                else:
                    params['unit_amount_decimal'] = self.plan['overage_unit_amount_decimal']
                    params['recurring']['meter'] = meter['id']
                prices[kind] = self.create(self.api.v1.prices, params, kind + '-price')
                validate_price(prices[kind], self.plan, product['id'], meter['id'], kind)
            self.remember(kind + '_price_id', prices[kind]['id'])
        if not webhook:
            webhook = self.create(self.api.v1.webhook_endpoints, {'url': self.plan['webhook_url'], 'enabled_events': EVENTS,
                'api_version': VERSION, 'metadata': OWNER, 'description': 'KWIP Data Marketplace subscription reconciliation v1'}, 'webhook')
            # Store the create-only secret immediately, before any later validation/failure.
            secret = webhook.get('secret')
            self.data.setdefault('objects', {})['webhook_id'] = webhook['id']
            if isinstance(secret, str) and secret.startswith('whsec_'):
                self.data.setdefault('config', {})['MARKET_STRIPE_WEBHOOK_SECRET'] = secret
            self.journal.save()
            validate_webhook(webhook, self.plan)
            if not isinstance(secret, str) or not secret.startswith('whsec_'):
                raise CommandError('Webhook created but secret unavailable; preserve journal and recover secret in Dashboard.')
        self.data['config'] = {'MARKET_STRIPE_PRO_PRICE_ID': prices['pro']['id'],
            'MARKET_STRIPE_OVERAGE_PRICE_ID': prices['overage']['id'], 'MARKET_STRIPE_METER_EVENT': self.plan['meter_event'],
            'MARKET_STRIPE_WEBHOOK_SECRET': secret, 'MARKET_STRIPE_LIVEMODE': self.plan['livemode'], 'MARKET_BILLING_ENABLED': False}
        self.data['objects']['webhook_id'] = webhook['id']
        self.data.update(status='configured_requires_uat', ready_for_sales=False,
            remaining=['Install private config in the matching deployment; do not commit it.',
                       'Verify signed webhook delivery and real sandbox Checkout/Portal/meter reconciliation.',
                       'Review tax, account eligibility and customer terms; configure Billing Portal separately.',
                       'Keep billing disabled until approved production data and release gates are satisfied.'])
        self.journal.save()


class Command(BaseCommand):
    help = 'Preview or provision NEW marketplace Stripe product/prices/meter/webhook; never enable billing or create charges.'

    def add_arguments(self, parser):
        mode_group = parser.add_mutually_exclusive_group()
        mode_group.add_argument('--dry-run', action='store_true', help='Offline intent only (default). No provider calls or files.')
        mode_group.add_argument('--apply', action='store_true', help='Explicitly create/reuse matching marketplace provider objects.')
        parser.add_argument('--output', help='Required with --apply: absolute outside-repository private JSON checkpoint/config file.')
        parser.add_argument('--existing-webhook-secret-env', help='Optional environment variable NAME containing a recovered existing endpoint secret.')

    def handle(self, *args, **options):
        plan = intent()
        if not options['apply']:
            self.stdout.write(json.dumps({'mode': 'offline_dry_run', 'intent': plan,
                'existing_provider_objects_checked': False, 'requires_apply_output': True,
                'changes': ['Create/reuse marketplace product, two monthly prices, sum meter and signed webhook.',
                            'Never modify old products, customers, subscriptions or account sales settings.']}, indent=2))
            return
        secret_env = options['existing_webhook_secret_env']
        if secret_env and not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,100}', secret_env):
            raise CommandError('Provide an environment variable name, never a secret value, for webhook recovery.')
        journal = Journal(options['output'])
        try:
            Setup(client(), plan, journal, secret_env).run()
        except (stripe.StripeError, Problem):
            raise CommandError('Provider setup could not complete. Preserve the private journal and retry identical settings after reviewing the provider; no secret or provider response is logged.') from None
        except OSError:
            raise CommandError('Private checkpoint write failed. Preserve the file and reconcile provider state before retrying; no provider objects were deleted.') from None
        finally:
            journal.close()
        self.stdout.write('Marketplace provider configuration saved privately. Billing remains disabled; UAT is still required. No customer or subscription was created.')
