import hashlib
import hmac
import json
from datetime import timedelta
from unittest.mock import Mock, patch
import pytest
import stripe
from django.test import RequestFactory, override_settings
from django.utils import timezone
from plane.access.auth import Principal
from plane.access.errors import Problem
from plane.access.models import Identity, Workspace
from plane.catalog.models import Dataset, SchemaVersion, Source
from .models import BillingAccount, Delivery, MeterOutbox, StripeEvent
from .services import deliver, usage_summary, calendar_period
from .stripe_gateway import checkout, dispatch_one, process_event, receive_event, reconcile_subscription
from . import views

pytestmark = pytest.mark.django_db


@pytest.fixture
def principal():
    identity = Identity.objects.create(subject='user_commerce')
    return Principal(Workspace.objects.create(owner=identity), 'session')


@pytest.fixture
def dataset():
    dataset = Dataset.objects.create(slug='jobs', title='Jobs', status='published')
    schema = SchemaVersion.objects.create(dataset=dataset, version=1, fields={'id': {'type': 'integer'}})
    Source.objects.create(dataset=dataset, schema=schema, slug='sample', name='Sample', url='https://example.com', rights_status='approved', attribution='Test', license_url='https://example.com/license')
    return dataset


def result(n):
    return {'records': [{'id': i, 'source': {'slug': 'sample'}} for i in range(n)], 'count': n, 'next_cursor': None}


def send(principal, dataset, n=1, key='r1', fingerprint='f1', **kwargs):
    return deliver(principal, dataset, key, fingerprint, lambda: result(n), **kwargs)


def pro(principal, **kwargs):
    now = timezone.now()
    start, end = calendar_period(now)
    defaults = dict(status='active', period_start=start, period_end=end, allowance_start=start,
                    stripe_customer_id='cus_test', stripe_subscription_id='sub_test', metered_item_active=True)
    defaults.update(kwargs)
    return BillingAccount.objects.create(workspace=principal.workspace, **defaults)


def test_free_receipt_replay_and_conflict(principal, dataset):
    response = send(principal, dataset, 3)
    assert response['usage']['credits'] == 3
    assert deliver(principal, dataset, 'r1', 'f1', Mock(side_effect=AssertionError)) == response
    assert Delivery.objects.count() == 1
    with pytest.raises(Problem, match='different request'):
        send(principal, dataset, fingerprint='changed')
    assert usage_summary(principal.workspace)['used_credits'] == 3
    assert not MeterOutbox.objects.exists()


def test_idempotency_is_workspace_and_dataset_bound(principal, dataset):
    send(principal, dataset)
    other = Principal(Workspace.objects.create(owner=Identity.objects.create(subject='user_other')), 'session')
    send(other, dataset)
    assert Delivery.objects.count() == 2
    with pytest.raises(Problem):
        send(principal, Dataset.objects.create(slug='different', title='Different', status='published'))


@override_settings(MARKET_FREE_CREDITS=2)
def test_quota_and_empty_results(principal, dataset):
    send(principal, dataset, 2)
    with pytest.raises(Problem) as exc:
        send(principal, dataset, key='r2')
    assert exc.value.code == 'quota_exceeded'
    assert send(principal, dataset, 0, key='empty')['usage']['credits'] == 0
    assert usage_summary(principal.workspace)['used_credits'] == 2


def test_failure_and_serialization_do_not_charge(principal, dataset):
    with pytest.raises(RuntimeError):
        deliver(principal, dataset, 'r1', 'f1', Mock(side_effect=RuntimeError))
    with pytest.raises(Problem):
        deliver(principal, dataset, 'r2', 'f2', lambda: {'records': [float('nan')]})
    assert not Delivery.objects.exists()


@override_settings(MARKET_MAX_DELIVERY_BYTES=100)
def test_response_limit_does_not_charge(principal, dataset):
    with pytest.raises(Problem) as exc:
        send(principal, dataset)
    assert exc.value.status == 413
    assert not Delivery.objects.exists()


def test_credit_weight_and_request_budget(principal, dataset):
    dataset.credits_per_record = 3
    dataset.save()
    with pytest.raises(Problem) as exc:
        send(principal, dataset, 2, max_credits=5)
    assert exc.value.code == 'request_budget_exceeded'
    assert send(principal, dataset, 2, max_credits=6)['usage']['credits'] == 6


@override_settings(MARKET_PRO_CREDITS=2, MARKET_BILLING_ENABLED=True)
def test_overage_optin_and_cap(principal, dataset):
    account = pro(principal)
    with pytest.raises(Problem):
        send(principal, dataset, 3)
    account.overage_enabled, account.spend_cap_cents = True, 1
    account.save()
    response = send(principal, dataset, 102)
    assert response['usage']['overage_credits'] == 100
    assert MeterOutbox.objects.get().delivery.overage_credits == 100
    with pytest.raises(Problem) as exc:
        send(principal, dataset, key='more')
    assert exc.value.code == 'spend_cap_exceeded'
    assert usage_summary(principal.workspace)['estimated_overage_cents'] == 1


@override_settings(MARKET_FREE_CREDITS=1, MARKET_PRO_CREDITS=2)
def test_plan_changes_do_not_reset_same_calendar_usage(principal, dataset):
    send(principal, dataset)
    account = BillingAccount.objects.get(workspace=principal.workspace)
    start, end = calendar_period(timezone.now())
    account.status, account.period_start, account.period_end, account.allowance_start = 'active', start, end, start
    account.save()
    send(principal, dataset, key='upgrade')
    account.status = 'canceled'
    account.save()
    assert usage_summary(principal.workspace)['used_credits'] == 2
    with pytest.raises(Problem):
        send(principal, dataset, key='downgrade')


def test_expired_pro_and_disabled_owner(principal, dataset):
    pro(principal, period_end=timezone.now() - timedelta(seconds=1))
    assert usage_summary(principal.workspace)['plan'] == 'free'
    principal.workspace.owner.active = False
    principal.workspace.owner.save()
    with pytest.raises(Problem) as exc:
        send(principal, dataset)
    assert exc.value.code == 'account_disabled'


@override_settings(MARKET_BILLING_ENABLED=True)
def test_empty_catalog_blocks_checkout_without_provider(principal):
    with patch('plane.commerce.stripe_gateway.client') as api:
        with pytest.raises(Problem) as exc:
            checkout(principal.workspace)
        assert exc.value.code == 'catalog_empty'
        api.assert_not_called()


@pytest.mark.parametrize('view', [views.checkout, views.portal, views.configure_overage])
def test_service_keys_cannot_manage_billing(principal, view):
    principal.kind = 'service'
    request = RequestFactory().post('/billing', data='{}', content_type='application/json')
    with patch('plane.access.http.authenticate', return_value=principal):
        response = view(request)
    assert response.status_code == 403


@override_settings(MARKET_PRO_CREDITS=0, MARKET_BILLING_ENABLED=True)
def make_outbox(principal, dataset):
    pro(principal, overage_enabled=True, spend_cap_cents=100)
    send(principal, dataset)
    return MeterOutbox.objects.get()


def test_meter_dispatch_is_idempotent(principal, dataset):
    row = make_outbox(principal, dataset)
    api = Mock()
    with patch('plane.commerce.stripe_gateway.client', return_value=api):
        assert dispatch_one(row.pk) == 'submitted'
        assert dispatch_one(row.pk) == 'submitted'
    api.v1.billing.meter_events.create.assert_called_once()
    args = api.v1.billing.meter_events.create.call_args
    assert args.args[0]['identifier'] == str(row.pk)
    assert args.args[0]['payload']['value'] == '1'
    assert args.kwargs['options']['idempotency_key'] == 'kwip-meter-' + str(row.pk)


def test_meter_timeout_retry_uses_same_identifier(principal, dataset):
    row = make_outbox(principal, dataset)
    api = Mock()
    api.v1.billing.meter_events.create.side_effect = stripe.APIConnectionError('timeout')
    with patch('plane.commerce.stripe_gateway.client', return_value=api):
        assert dispatch_one(row.pk) == 'pending'
        MeterOutbox.objects.filter(pk=row.pk).update(next_attempt_at=None)
        api.v1.billing.meter_events.create.side_effect = None
        assert dispatch_one(row.pk) == 'submitted'
    assert api.v1.billing.meter_events.create.call_args_list[0] == api.v1.billing.meter_events.create.call_args_list[1]


def test_old_ambiguous_meter_requires_review(principal, dataset):
    row = make_outbox(principal, dataset)
    row.first_attempt_at = timezone.now() - timedelta(hours=24)
    row.save()
    with patch('plane.commerce.stripe_gateway.client') as api:
        assert dispatch_one(row.pk) == 'review'
        api.assert_not_called()


def test_meter_validation_failure_requires_review(principal, dataset):
    row = make_outbox(principal, dataset)
    api = Mock()
    api.v1.billing.meter_events.create.side_effect = stripe.InvalidRequestError('bad meter', 'meter', http_status=400)
    with patch('plane.commerce.stripe_gateway.client', return_value=api):
        assert dispatch_one(row.pk) == 'review'


def signed_event(payload, secret='whsec_fake'):
    raw = json.dumps(payload).encode()
    timestamp = int(timezone.now().timestamp())
    signature = hmac.new(secret.encode(), str(timestamp).encode() + b'.' + raw, hashlib.sha256).hexdigest()
    return raw, f't={timestamp},v1={signature}'


@override_settings(MARKET_STRIPE_WEBHOOK_SECRET='whsec_fake', MARKET_STRIPE_LIVEMODE=False)
def test_webhook_signature_duplicate_and_environment():
    raw, sig = signed_event({'id': 'evt_fake', 'type': 'invoice.paid', 'livemode': False, 'data': {'object': {}}})
    receive_event(raw, sig)
    receive_event(raw, sig)
    assert StripeEvent.objects.count() == 1
    with pytest.raises(Problem):
        receive_event(raw + b' ', sig)
    raw, sig = signed_event({'id': 'evt_live', 'type': 'invoice.paid', 'livemode': True, 'data': {'object': {}}})
    with pytest.raises(Problem):
        receive_event(raw, sig)


def test_webhook_duplicate_reconciliation_and_unknown_customer(principal):
    account = pro(principal)
    event = StripeEvent.objects.create(event_id='evt_test', event_type='invoice.paid', payload={'data': {'object': {'customer': 'cus_test', 'subscription': 'sub_test'}}})
    with patch('plane.commerce.stripe_gateway.reconcile_subscription') as reconcile:
        process_event(event.pk)
        process_event(event.pk)
        reconcile.assert_called_once_with(account.pk, 'sub_test')
    event = StripeEvent.objects.create(event_id='evt_other', event_type='invoice.paid', payload={'data': {'object': {'customer': 'cus_other'}}})
    with patch('plane.commerce.stripe_gateway.reconcile_subscription') as reconcile:
        process_event(event.pk)
        reconcile.assert_not_called()


def subscription(account, status='active', paid=True):
    return {'id': 'sub_test', 'customer': 'cus_test', 'livemode': False, 'currency': 'usd', 'status': status,
            'latest_invoice': {'status': 'paid' if paid else 'open'},
            'items': {'data': [{'quantity': 1, 'price': {'id': 'price_pro'},
                'current_period_start': int(account.period_start.timestamp()), 'current_period_end': int(account.period_end.timestamp())},
                {'price': {'id': 'price_meter'}}]}}


@override_settings(MARKET_STRIPE_PRO_PRICE_ID='price_pro', MARKET_STRIPE_OVERAGE_PRICE_ID='price_meter', MARKET_STRIPE_LIVEMODE=False)
@pytest.mark.parametrize('status,paid,expected', [('active', True, 'active'), ('active', False, 'payment_unverified'), ('past_due', False, 'past_due'), ('canceled', True, 'canceled'), ('incomplete', False, 'incomplete')])
def test_subscription_current_state_governs_access(principal, status, paid, expected):
    account = pro(principal, overage_enabled=True)
    api = Mock()
    api.v1.subscriptions.retrieve.return_value = subscription(account, status, paid)
    with patch('plane.commerce.stripe_gateway.client', return_value=api), patch('plane.commerce.stripe_gateway.validate_prices'):
        reconcile_subscription(account.pk)
    account.refresh_from_db()
    assert account.status == expected
    if expected != 'active':
        assert not account.overage_enabled
        assert not account.metered_item_active


@override_settings(MARKET_STRIPE_PRO_PRICE_ID='price_pro', MARKET_STRIPE_OVERAGE_PRICE_ID='price_meter')
def test_foreign_subscription_never_entitles(principal):
    account = pro(principal)
    api = Mock()
    obj = subscription(account)
    obj['customer'] = 'cus_other'
    api.v1.subscriptions.retrieve.return_value = obj
    with patch('plane.commerce.stripe_gateway.client', return_value=api), pytest.raises(Problem):
        reconcile_subscription(account.pk)


def test_replay_denied_after_withdrawal_or_expiry(principal, dataset):
    send(principal, dataset)
    dataset.sources.update(rights_status='blocked')
    with pytest.raises(Problem) as exc:
        send(principal, dataset)
    assert exc.value.code == 'source_unavailable'
    dataset.sources.update(rights_status='approved')
    Delivery.objects.update(created_at=timezone.now() - timedelta(hours=25))
    with pytest.raises(Problem) as exc:
        send(principal, dataset)
    assert exc.value.code == 'receipt_expired'
    assert Delivery.objects.count() == 1


def test_cache_purge_keeps_idempotency_tombstone(principal, dataset):
    from django.core.management import call_command
    send(principal, dataset)
    Delivery.objects.update(created_at=timezone.now() - timedelta(hours=25))
    call_command('purge_delivery_cache')
    assert Delivery.objects.get().response == {}
    with pytest.raises(Problem) as exc:
        send(principal, dataset)
    assert exc.value.code == 'receipt_expired'


def test_dataset_price_refreshed_under_lock(principal, dataset):
    Dataset.objects.filter(pk=dataset.pk).update(credits_per_record=5)
    assert send(principal, dataset)['usage']['credits'] == 5


def test_replay_honors_narrowed_key_restrictions(principal, dataset):
    from plane.access.auth import issue_key
    send(principal, dataset)
    key, _ = issue_key(principal.workspace, 'Restricted', ['datasets:read'], dataset_slugs=['elsewhere'])
    service = Principal(principal.workspace, 'service', key)
    with pytest.raises(Problem) as exc:
        send(service, dataset)
    assert exc.value.code == 'dataset_forbidden'
    key.dataset_slugs, key.source_slugs = [], ['other-source']
    key.save()
    with pytest.raises(Problem) as exc:
        send(service, dataset)
    assert exc.value.code == 'source_forbidden'


def test_reconcile_meter_records_mismatch_without_adjustment(principal, dataset):
    from .stripe_gateway import reconcile_meter
    row = make_outbox(principal, dataset)
    Delivery.objects.filter(pk=row.pk).update(created_at=timezone.now() - timedelta(minutes=30))
    MeterOutbox.objects.filter(pk=row.pk).update(status='submitted')
    api = Mock()
    api.v1.prices.retrieve.return_value = {'recurring': {'meter': 'mtr_test'}}
    api.v1.billing.meters.event_summaries.list.return_value = {'data': [{'aggregated_value': 2}], 'has_more': False}
    with patch('plane.commerce.stripe_gateway.client', return_value=api):
        record = reconcile_meter(principal.workspace.pk)
    assert record.status == 'mismatch'
    assert record.expected_credits == 1
    assert record.remote_credits == 2
    assert MeterOutbox.objects.count() == 1
    api.v1.billing.meter_events.create.assert_not_called()


@pytest.mark.django_db(transaction=True)
@override_settings(MARKET_FREE_CREDITS=1)
def test_postgres_concurrent_last_credit(principal, dataset):
    from concurrent.futures import ThreadPoolExecutor
    from django.db import connection, close_old_connections
    if connection.vendor != 'postgresql':
        pytest.skip('Row-lock concurrency requires PostgreSQL.')
    def request(key):
        close_old_connections()
        try:
            try:
                send(principal, dataset, key=key)
                return 'delivered'
            except Problem as exc:
                return exc.code
        finally:
            from django.db import connections
            connections.close_all()
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(request, ['concurrent-a', 'concurrent-b']))
    assert sorted(outcomes) == ['delivered', 'quota_exceeded']
    assert Delivery.objects.count() == 1


def price_api():
    api = Mock()
    api.v1.prices.retrieve.side_effect = [
        {'id': 'price_pro', 'active': True, 'livemode': False, 'currency': 'usd', 'unit_amount': 2900,
         'recurring': {'interval': 'month', 'interval_count': 1, 'usage_type': 'licensed'}},
        {'id': 'price_meter', 'active': True, 'livemode': False, 'currency': 'usd', 'unit_amount_decimal': '0.010000000000',
         'billing_scheme': 'per_unit', 'recurring': {'interval': 'month', 'interval_count': 1, 'usage_type': 'metered', 'meter': 'mtr_test'}}]
    api.v1.billing.meters.retrieve.return_value = {'event_name': 'kwip_overage_credits', 'status': 'active', 'default_aggregation': {'formula': 'sum'}}
    return api


@override_settings(MARKET_STRIPE_PRO_PRICE_ID='price_pro', MARKET_STRIPE_OVERAGE_PRICE_ID='price_meter', MARKET_STRIPE_LIVEMODE=False)
def test_price_precision_and_rejected_mispricing():
    from .stripe_gateway import validate_prices
    api = price_api()
    validate_prices(api)
    assert api.v1.prices.retrieve.call_args_list[1].args == ('price_meter',)
    with override_settings(MARKET_OVERAGE_CENTS_PER_10000=101), pytest.raises(Problem):
        validate_prices(price_api())


@pytest.mark.django_db(transaction=True)
@override_settings(MARKET_FREE_CREDITS=1)
def test_postgres_concurrent_identical_receipt(principal, dataset):
    from concurrent.futures import ThreadPoolExecutor
    from django.db import connection, close_old_connections
    if connection.vendor != 'postgresql':
        pytest.skip('Row-lock concurrency requires PostgreSQL.')
    def request(_):
        close_old_connections()
        try:
            return send(principal, dataset, key='same-request')['usage']['receipt_id']
        finally:
            from django.db import connections
            connections.close_all()
    with ThreadPoolExecutor(max_workers=2) as executor:
        receipts = list(executor.map(request, range(2)))
    assert receipts[0] == receipts[1]
    assert Delivery.objects.count() == 1


@pytest.mark.django_db(transaction=True)
@override_settings(MARKET_PRO_CREDITS=0, MARKET_BILLING_ENABLED=True)
def test_postgres_meter_workers_serialize_customer(principal, dataset):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from django.db import connection, close_old_connections
    if connection.vendor != 'postgresql':
        pytest.skip('Row-lock concurrency requires PostgreSQL.')
    pro(principal, overage_enabled=True, spend_cap_cents=100)
    send(principal, dataset, key='first')
    send(principal, dataset, key='second')
    first, second = list(MeterOutbox.objects.order_by('delivery__created_at'))
    entered, release = Event(), Event()
    api = Mock()
    def remote(*args, **kwargs):
        entered.set()
        assert release.wait(5)
    api.v1.billing.meter_events.create.side_effect = remote
    def worker(pk):
        close_old_connections()
        try:
            return dispatch_one(pk)
        finally:
            from django.db import connections
            connections.close_all()
    with patch('plane.commerce.stripe_gateway.client', return_value=api), ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(worker, first.pk)
        try:
            assert entered.wait(5)
            assert dispatch_one(second.pk) == 'busy'
        finally:
            release.set()
        assert future.result() == 'submitted'
        assert dispatch_one(second.pk) == 'submitted'
    assert api.v1.billing.meter_events.create.call_count == 2


def test_disabling_overage_retains_consent_history(principal):
    from .models import BillingConsent
    pro(principal, overage_enabled=True, spend_cap_cents=100)
    request = RequestFactory().post('/billing', data=json.dumps({'enabled': False, 'spend_cap_cents': 0}), content_type='application/json')
    with patch('plane.access.http.authenticate', return_value=principal):
        response = views.configure_overage(request)
    assert response.status_code == 200
    receipt = BillingConsent.objects.get()
    assert not receipt.overage_enabled
    assert receipt.identity == principal.workspace.owner
    assert usage_summary(principal.workspace)['billing_account_exists']


@override_settings(MARKET_STRIPE_SECRET_KEY='sk_test_fixture_only', MARKET_STRIPE_LIVEMODE=False)
def test_real_stripe_sdk_serializes_meter_endpoint_and_idempotency(principal, dataset):
    from urllib.parse import parse_qs
    row = make_outbox(principal, dataset)
    response = json.dumps({'object': 'billing.meter_event', 'identifier': str(row.pk)}).encode()
    # Real SDK serialization, fake HTTP transport: no provider request is possible.
    with patch.object(stripe.RequestsClient, 'request', return_value=(response, 200, {})) as request:
        assert dispatch_one(row.pk) == 'submitted'
    method, url, headers, body = request.call_args.args
    assert method == 'post'
    assert url == 'https://api.stripe.com/v1/billing/meter_events'
    assert headers['Idempotency-Key'] == 'kwip-meter-' + str(row.pk)
    assert headers['Stripe-Version'] == '2026-02-25.clover'
    values = parse_qs(body)
    assert values['payload[value]'] == ['1']
    assert values['payload[stripe_customer_id]'] == ['cus_test']
    assert values['identifier'] == [str(row.pk)]


@override_settings(MARKET_BILLING_ENABLED=True, MARKET_STRIPE_PRO_PRICE_ID='price_pro', MARKET_STRIPE_OVERAGE_PRICE_ID='price_meter')
def test_checkout_reuses_session_and_trusted_customer(principal):
    api = Mock()
    api.v1.customers.create.return_value = {'id': 'cus_created'}
    api.v1.subscriptions.list.return_value = {'data': [], 'has_more': False}
    api.v1.checkout.sessions.create.return_value = {'id': 'cs_created', 'url': 'https://checkout.stripe.com/test', 'expires_at': int((timezone.now() + timedelta(hours=24)).timestamp())}
    with patch('plane.commerce.stripe_gateway.available_data', return_value=True), patch('plane.commerce.stripe_gateway.client', return_value=api), patch('plane.commerce.stripe_gateway.validate_prices'):
        first = checkout(principal.workspace)
        assert checkout(principal.workspace) == first
    api.v1.checkout.sessions.create.assert_called_once()
    params = api.v1.checkout.sessions.create.call_args.args[0]
    assert params['customer'] == 'cus_created'
    assert params['line_items'] == [{'price': 'price_pro', 'quantity': 1}, {'price': 'price_meter'}]
    assert BillingAccount.objects.get().status == 'free'
    assert not BillingAccount.objects.get().overage_enabled


@override_settings(MARKET_BILLING_ENABLED=True, MARKET_STRIPE_PRO_PRICE_ID='price_pro', MARKET_STRIPE_OVERAGE_PRICE_ID='price_meter')
def test_checkout_blocks_provider_subscription_before_webhook(principal):
    BillingAccount.objects.create(workspace=principal.workspace, stripe_customer_id='cus_test')
    api = Mock()
    api.v1.subscriptions.list.return_value = {'data': [{'status': 'active'}], 'has_more': False}
    with patch('plane.commerce.stripe_gateway.available_data', return_value=True), patch('plane.commerce.stripe_gateway.client', return_value=api), patch('plane.commerce.stripe_gateway.validate_prices'), pytest.raises(Problem) as exc:
        checkout(principal.workspace)
    assert exc.value.code == 'subscription_exists'
    api.v1.checkout.sessions.create.assert_not_called()


def test_signed_deletion_creates_durable_cancellation_and_retries(principal):
    from plane.access.webhooks import apply_event
    from .stripe_gateway import reconcile_deleted_account
    account = pro(principal, overage_enabled=True, spend_cap_cents=100)
    apply_event('msg_billing_delete', {'type': 'user.deleted', 'data': {'id': principal.workspace.owner.subject}})
    account.refresh_from_db()
    assert account.cancellation_requested_at
    assert not account.overage_enabled
    api = Mock()
    api.v1.checkout.sessions.list.return_value = {'data': [{'id': 'cs_open', 'mode': 'subscription', 'client_reference_id': str(account.pk)}], 'has_more': False}
    api.v1.subscriptions.list.return_value = {'data': [{'id': 'sub_test', 'status': 'active', 'metadata': {'kwip_workspace': str(account.pk)}}], 'has_more': False}
    api.v1.subscriptions.cancel.side_effect = stripe.APIConnectionError('timeout')
    with pytest.raises(stripe.APIConnectionError):
        reconcile_deleted_account(account.pk, api=api)
    account.refresh_from_db()
    assert account.cancellation_requested_at and not account.cancellation_completed_at
    # Provider now reports the checkout expired and the subscription still active.
    api.v1.checkout.sessions.list.return_value = {'data': [], 'has_more': False}
    api.v1.subscriptions.cancel.side_effect = None
    reconcile_deleted_account(account.pk, api=api)
    reconcile_deleted_account(account.pk, api=api)
    account.refresh_from_db()
    assert account.cancellation_completed_at
    assert account.status == 'canceled'
    assert api.v1.subscriptions.cancel.call_count == 2
    api.v1.subscriptions.cancel.assert_called_with('sub_test', params={'invoice_now': False, 'prorate': False})
    assert not account.metered_item_active


def test_deletion_cancels_subscription_before_local_webhook_mapping(principal):
    from plane.access.webhooks import apply_event
    from .stripe_gateway import reconcile_deleted_account
    account = BillingAccount.objects.create(workspace=principal.workspace, stripe_customer_id='cus_pending')
    apply_event('msg_pending_delete', {'type': 'user.deleted', 'data': {'id': principal.workspace.owner.subject}})
    api = Mock()
    api.v1.checkout.sessions.list.return_value = {'data': [], 'has_more': False}
    api.v1.subscriptions.list.return_value = {'data': [{'id': 'sub_pending', 'status': 'incomplete', 'metadata': {}}], 'has_more': False}
    reconcile_deleted_account(account.pk, api=api)
    api.v1.subscriptions.cancel.assert_called_once()
    account.refresh_from_db()
    assert account.cancellation_completed_at
