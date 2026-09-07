"""Bounded Stripe SDK calls. Never pass user-supplied price/customer IDs through."""
from datetime import timedelta
import json
import secrets
from decimal import Decimal, InvalidOperation
import stripe
from django.db import transaction
from django.utils import timezone
from plane.access.errors import Problem
from plane.access.models import Workspace
from .models import BillingAccount, StripeEvent, MeterOutbox
from .services import option, account_for, available_data, calendar_period, unix_datetime


def client():
    key = option('STRIPE_SECRET_KEY', '')
    if not key:
        raise Problem('billing_unavailable', 'Billing is not configured.', 503)
    live = bool(option('STRIPE_LIVEMODE', False))
    if ('_live_' in key) != live or not any(marker in key for marker in ('_live_', '_test_')):
        raise Problem('billing_unavailable', 'Billing environment does not match its credential.', 503)
    return stripe.StripeClient(key, max_network_retries=0, stripe_version='2026-02-25.clover', http_client=stripe.RequestsClient(timeout=10))


def require_sales():
    if not option('BILLING_ENABLED', False):
        raise Problem('billing_unavailable', 'Paid plans are not enabled yet.', 503)
    if not available_data():
        raise Problem('catalog_empty', 'Paid plans are unavailable while the catalog has no data.', 409)
    if not option('STRIPE_PRO_PRICE_ID', '') or not option('STRIPE_OVERAGE_PRICE_ID', ''):
        raise Problem('billing_unavailable', 'Plan prices are not configured.', 503)


def validate_prices(api):
    fixed = api.v1.prices.retrieve(option('STRIPE_PRO_PRICE_ID'))
    metered = api.v1.prices.retrieve(option('STRIPE_OVERAGE_PRICE_ID'))
    expected_mode = bool(option('STRIPE_LIVEMODE', False))
    for price in (fixed, metered):
        if not price.get('active') or price.get('currency') != 'usd' or price.get('livemode') != expected_mode:
            raise Problem('billing_unavailable', 'Configured price is not active in this environment.', 503)
        recurring = price.get('recurring') or {}
        if recurring.get('interval') != 'month' or recurring.get('interval_count', 1) != 1:
            raise Problem('billing_unavailable', 'Configured prices must be monthly.', 503)
    if fixed.get('unit_amount') != option('PRO_MONTHLY_CENTS', 2900) or fixed['recurring'].get('usage_type') != 'licensed':
        raise Problem('billing_unavailable', 'Pro pricing configuration does not match the plan.', 503)
    rate = Decimal(option('OVERAGE_CENTS_PER_10000', 100)) / Decimal(10000)
    try:
        actual_rate = Decimal(str(metered.get('unit_amount_decimal')))
    except InvalidOperation as exc:
        raise Problem('billing_unavailable', 'Invalid metered unit price.', 503) from exc
    if actual_rate != rate or metered['recurring'].get('usage_type') != 'metered' or metered.get('billing_scheme') != 'per_unit':
        raise Problem('billing_unavailable', 'Overage pricing configuration does not match the plan.', 503)
    meter_id = metered['recurring'].get('meter')
    if not meter_id:
        raise Problem('billing_unavailable', 'Overage price must use a billing meter.', 503)
    meter = api.v1.billing.meters.retrieve(meter_id)
    if meter.get('event_name') != option('STRIPE_METER_EVENT', 'kwip_overage_credits') or meter.get('default_aggregation', {}).get('formula') != 'sum' or meter.get('status') != 'active':
        raise Problem('billing_unavailable', 'Meter configuration does not match the plan.', 503)


def checkout(workspace):
    require_sales()
    api = client()
    validate_prices(api)
    with transaction.atomic():
        Workspace.objects.select_for_update().get(pk=workspace.pk)
        account = account_for(workspace)
        if account.stripe_subscription_id and account.status not in ('free', 'canceled', 'incomplete_expired'):
            raise Problem('subscription_exists', 'Manage your existing subscription through Billing.', 409)
        if account.checkout_url and account.checkout_expires_at and account.checkout_expires_at > timezone.now():
            return {'url': account.checkout_url}
        if account.checkout_expires_at and account.checkout_expires_at <= timezone.now():
            import uuid
            account.checkout_generation = uuid.uuid4()
            account.checkout_session_id = account.checkout_url = ''
        account.checkout_expires_at = timezone.now() + timedelta(hours=1)
        account.save()
        generation, customer_id = str(account.checkout_generation), account.stripe_customer_id
    if not customer_id:
        customer = api.v1.customers.create({'metadata': {'kwip_workspace': str(workspace.pk)}},
                                          options={'idempotency_key': 'kwip-customer-' + str(workspace.pk)})
        customer_id = customer['id']
        with transaction.atomic():
            Workspace.objects.select_for_update().get(pk=workspace.pk)
            account = account_for(workspace)
            if account.stripe_customer_id and account.stripe_customer_id != customer_id:
                raise Problem('billing_conflict', 'Billing identity needs reconciliation.', 409)
            account.stripe_customer_id = customer_id
            account.save(update_fields=['stripe_customer_id'])
    existing = api.v1.subscriptions.list(params={'customer': customer_id, 'status': 'all', 'limit': 100})
    if existing.get('has_more') or any(sub.get('status') not in ('canceled', 'incomplete_expired') for sub in existing.get('data', [])):
        raise Problem('subscription_exists', 'A subscription already exists. Use Billing to manage it.', 409)
    origin = option('ORIGIN', 'https://kwip.tech').rstrip('/')
    with transaction.atomic():
        locked = Workspace.objects.select_for_update().select_related('owner').get(pk=workspace.pk)
        if not locked.owner.active or locked.owner.deleted_at:
            raise Problem('account_disabled', 'This account is disabled.', 403)
        result = api.v1.checkout.sessions.create({'mode': 'subscription', 'customer': customer_id,
            'line_items': [{'price': option('STRIPE_PRO_PRICE_ID'), 'quantity': 1}, {'price': option('STRIPE_OVERAGE_PRICE_ID')}],
            'subscription_data': {'metadata': {'kwip_workspace': str(workspace.pk)}},
            'custom_text': {'submit': {'message': (
                f"Pro includes {option('PRO_CREDITS', 100000):,} credits per billing month. "
                'Paid overage stays off until you enable it in your KWIP Account, with an explicit spending cap.')}},
            'client_reference_id': str(workspace.pk), 'success_url': origin + '/account?billing=return',
            'cancel_url': origin + '/account?billing=cancel'}, options={'idempotency_key': 'kwip-checkout-' + generation})
        BillingAccount.objects.filter(workspace=workspace, checkout_generation=generation).update(
            checkout_session_id=result['id'], checkout_url=result['url'], checkout_expires_at=unix_datetime(result['expires_at']))
    return {'url': result['url']}


def portal(workspace):
    account = account_for(workspace)
    if not account.stripe_customer_id:
        raise Problem('no_billing_account', 'No Stripe billing account exists yet.', 409)
    params = {'customer': account.stripe_customer_id,
              'return_url': option('ORIGIN', 'https://kwip.tech').rstrip('/') + '/account'}
    configuration = option('STRIPE_PORTAL_CONFIGURATION_ID', '')
    if configuration:
        params['configuration'] = configuration
    result = client().v1.billing_portal.sessions.create(params)
    return {'url': result['url']}


def reconcile_subscription(account_id, subscription_id=None):
    api = client()
    # Serialize provider refreshes with delivery/configuration so an older in-flight read
    # cannot overwrite a later one. This infrequent control-plane call has bounded timeout.
    with transaction.atomic():
        Workspace.objects.select_for_update().get(pk=account_id)
        account = BillingAccount.objects.select_for_update().get(workspace_id=account_id)
        if account.workspace.owner.deleted_at:
            return reconcile_deleted_account(account.pk, api=api)
        sub_id = subscription_id or account.stripe_subscription_id
        if not sub_id:
            return
        sub = api.v1.subscriptions.retrieve(sub_id, params={'expand': ['latest_invoice']})
        if sub.get('customer') != account.stripe_customer_id or sub.get('livemode') != bool(option('STRIPE_LIVEMODE', False)):
            raise Problem('billing_identity_mismatch', 'Subscription does not belong to the expected account.', 409)
        if account.stripe_subscription_id and account.stripe_subscription_id != sub_id and account.status not in ('free', 'canceled', 'incomplete_expired'):
            raise Problem('billing_subscription_conflict', 'A different subscription is already associated.', 409)
        items = sub.get('items', {}).get('data', [])
        fixed = next((item for item in items if item.get('price', {}).get('id') == option('STRIPE_PRO_PRICE_ID')), None)
        metered = next((item for item in items if item.get('price', {}).get('id') == option('STRIPE_OVERAGE_PRICE_ID')), None)
        valid = bool(fixed and metered and len(items) == 2 and fixed.get('quantity') == 1 and sub.get('currency') == 'usd')
        invoice = sub.get('latest_invoice') or {}
        paid = isinstance(invoice, dict) and invoice.get('status') == 'paid'
        # StripeObject is dict-compatible. Never grant on checkout return or incomplete payment.
        status = sub.get('status', 'unknown')
        start_value = (fixed or {}).get('current_period_start', sub.get('current_period_start'))
        end_value = (fixed or {}).get('current_period_end', sub.get('current_period_end'))
        if valid and paid and status == 'active' and start_value and end_value:
            validate_prices(api)
            start, end = unix_datetime(start_value), unix_datetime(end_value)
            if account.period_start != start:
                account.allowance_start = min(calendar_period(timezone.now())[0], start) if (not account.period_start or account.stripe_subscription_id != sub_id) else start
            account.period_start, account.period_end, account.status = start, end, 'active'
            account.metered_item_active = True
        else:
            account.status = status if status != 'active' else 'payment_unverified'
            account.metered_item_active = False
            account.overage_enabled = False
        account.stripe_subscription_id = sub_id
        account.reconciled_at = timezone.now()
        account.save()


def receive_event(body, signature):
    secret = option('STRIPE_WEBHOOK_SECRET', '')
    if not secret:
        raise Problem('webhook_unavailable', 'Webhook is not configured.', 503)
    try:
        stripe.Webhook.construct_event(body, signature, secret)
    except (ValueError, stripe.SignatureVerificationError) as exc:
        raise Problem('invalid_signature', 'Invalid Stripe webhook signature.', 400) from exc
    payload = json.loads(body)
    if payload.get('livemode') != bool(option('STRIPE_LIVEMODE', False)):
        raise Problem('wrong_environment', 'Webhook environment mismatch.', 400)
    row, _ = StripeEvent.objects.get_or_create(event_id=payload['id'], defaults={'event_type': payload['type'], 'payload': payload})
    return row


def process_event(event_id):
    event = StripeEvent.objects.get(pk=event_id)
    if event.status == 'processed':
        return
    obj = event.payload.get('data', {}).get('object', {})
    customer = obj.get('customer')
    relevant = event.event_type.startswith('customer.subscription.') or event.event_type in (
        'checkout.session.completed', 'invoice.paid', 'invoice.payment_failed', 'invoice.payment_action_required')
    account = BillingAccount.objects.filter(stripe_customer_id=customer).first() if customer else None
    try:
        if relevant and account:
            sub_id = obj.get('id') if event.event_type.startswith('customer.subscription.') else obj.get('subscription')
            sub_id = sub_id or obj.get('parent', {}).get('subscription_details', {}).get('subscription')
            reconcile_subscription(account.pk, sub_id)
        StripeEvent.objects.filter(pk=event.pk).update(status='processed', processed_at=timezone.now(), error_code='')
    except (stripe.StripeError, Problem, ValueError) as exc:
        StripeEvent.objects.filter(pk=event.pk).update(status='failed', error_code=type(exc).__name__)
        raise


def dispatch_one(outbox_id):
    now = timezone.now()
    workspace_id = MeterOutbox.objects.values_list('delivery__workspace_id', flat=True).get(pk=outbox_id)
    with transaction.atomic():
        Workspace.objects.select_for_update().get(pk=workspace_id)
        row = MeterOutbox.objects.select_for_update().select_related('delivery').get(pk=outbox_id)
        if MeterOutbox.objects.filter(customer_id=row.customer_id, status='leased', lease_until__gt=now).exclude(pk=row.pk).exists():
            return 'busy'
        if row.status in ('submitted', 'review') or (row.lease_until and row.lease_until > now) or (row.next_attempt_at and row.next_attempt_at > now):
            return row.status
        if row.first_attempt_at and now - row.first_attempt_at >= timedelta(hours=23):
            row.status, row.error_code = 'review', 'deduplication_window'
            row.save(update_fields=['status', 'error_code'])
            return 'review'
        row.first_attempt_at = row.first_attempt_at or now
        row.status, row.lease_until = 'leased', now + timedelta(minutes=2)
        row.attempts += 1
        row.save()
        params = {'event_name': row.event_name, 'identifier': str(row.pk),
                  'timestamp': int(row.delivery.created_at.timestamp()),
                  'payload': {'stripe_customer_id': row.customer_id, 'value': str(row.delivery.overage_credits)}}
    try:
        client().v1.billing.meter_events.create(params, options={'idempotency_key': 'kwip-meter-' + str(row.pk)})
    except (stripe.StripeError, Problem) as exc:
        code = getattr(exc, 'http_status', None)
        status = 'review' if code and 400 <= code < 500 and code != 429 else 'pending'
        MeterOutbox.objects.filter(pk=row.pk).update(status=status, lease_until=None,
            error_code=type(exc).__name__, next_attempt_at=now + timedelta(seconds=min(3600, 2 ** min(row.attempts, 11)) + secrets.randbelow(10)))
        return status
    MeterOutbox.objects.filter(pk=row.pk).update(status='submitted', submitted_at=timezone.now(), lease_until=None, error_code='')
    return 'submitted'


def reconcile_meter(account_id):
    """Compare settled windows only; record discrepancies, never synthesize charges."""
    from django.db.models import Sum
    from .models import Delivery, MeterReconciliation
    account = BillingAccount.objects.get(workspace_id=account_id)
    if not account.stripe_customer_id or not account.period_start or not account.period_end:
        return None
    start = account.period_start.replace(second=0, microsecond=0)
    end = min(account.period_end, timezone.now() - timedelta(minutes=15)).replace(second=0, microsecond=0)
    if end <= start:
        return None
    api = client()
    price = api.v1.prices.retrieve(option('STRIPE_OVERAGE_PRICE_ID'))
    meter_id = (price.get('recurring') or {}).get('meter')
    if not meter_id:
        raise Problem('billing_unavailable', 'No usage meter is configured.', 503)
    summary = api.v1.billing.meters.event_summaries.list(meter_id,
        params={'customer': account.stripe_customer_id, 'start_time': int(start.timestamp()), 'end_time': int(end.timestamp()), 'limit': 100})
    if summary.get('has_more'):
        raise Problem('reconciliation_incomplete', 'Usage summary requires manual pagination.', 503)
    remote = sum((Decimal(str(row['aggregated_value'])) for row in summary.get('data', [])), Decimal(0))
    deliveries = Delivery.objects.filter(workspace_id=account_id, created_at__gte=start, created_at__lt=end)
    expected = deliveries.aggregate(total=Sum('overage_credits'))['total'] or 0
    unresolved = MeterOutbox.objects.filter(delivery__in=deliveries).exclude(status='submitted').exists()
    status = 'unsettled' if unresolved else ('matched' if remote == expected else 'mismatch')
    record, _ = MeterReconciliation.objects.update_or_create(workspace_id=account_id, start_at=start, end_at=end,
        defaults={'expected_credits': expected, 'remote_credits': remote, 'status': status})
    return record


def reconcile_deleted_account(account_id, api=None):
    """Stop future renewals and expire unconsumed Checkouts after signed deletion.

    Permanent local pending state survives transient failures. No immediate invoice
    or prorated charge is requested; earned usage receipts remain for staff review.
    """
    api = api or client()
    with transaction.atomic():
        Workspace.objects.select_for_update().get(pk=account_id)
        account = BillingAccount.objects.select_for_update().select_related('workspace__owner').get(workspace_id=account_id)
        if not account.workspace.owner.deleted_at or account.cancellation_completed_at:
            return
        if not account.cancellation_requested_at:
            account.cancellation_requested_at = timezone.now()
            account.save(update_fields=['cancellation_requested_at'])
        if account.stripe_customer_id:
            sessions = api.v1.checkout.sessions.list(params={'customer': account.stripe_customer_id, 'status': 'open', 'limit': 100})
            if sessions.get('has_more'):
                raise Problem('cancellation_review_required', 'More Checkout sessions require operator review.', 503)
            for session in sessions.get('data', []):
                if session.get('mode') == 'subscription' and session.get('client_reference_id') == str(account_id):
                    api.v1.checkout.sessions.expire(session['id'])
            subscriptions = api.v1.subscriptions.list(params={'customer': account.stripe_customer_id, 'status': 'all', 'limit': 100})
            if subscriptions.get('has_more'):
                raise Problem('cancellation_review_required', 'More subscriptions require operator review.', 503)
            for sub in subscriptions.get('data', []):
                if sub.get('status') in ('canceled', 'incomplete_expired'):
                    continue
                # This customer belongs to the marketplace workspace. Reject any
                # conflicting provider metadata rather than cancel a stranger.
                if sub.get('metadata', {}).get('kwip_workspace') not in (None, str(account_id)):
                    raise Problem('billing_identity_mismatch', 'Subscription ownership needs review.', 409)
                api.v1.subscriptions.cancel(sub['id'], params={'invoice_now': False, 'prorate': False})
        account.status, account.overage_enabled, account.metered_item_active = 'canceled', False, False
        account.cancellation_completed_at = timezone.now()
        account.save(update_fields=['status', 'overage_enabled', 'metered_item_active', 'cancellation_completed_at'])
