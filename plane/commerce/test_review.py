"""Regression cases found during the final independent backend review."""
from datetime import datetime, timedelta, timezone as tz
from unittest.mock import Mock, patch
import pytest
from django.test import override_settings
from django.utils import timezone
from plane.access.auth import Principal, issue_key
from plane.access.errors import Problem
from plane.access.models import ServiceKey
from plane.commerce.models import BillingAccount
from plane.commerce.services import deliver
from plane.commerce.stripe_gateway import reconcile_subscription
from plane.exports.test_exports import example as export_example_fixture, seed
from plane.exports.services import create_export, process_page, download

pytestmark = pytest.mark.django_db
example = export_example_fixture


def test_revoked_stale_principal_cannot_deliver_or_replay(example):
    browser, dataset, source = example
    key, _ = issue_key(browser.workspace, 'Agent', ['datasets:read'])
    principal = Principal(browser.workspace, 'service', key)
    producer = lambda: {'records': [{'source': {'slug': source.slug}}], 'count': 1}
    deliver(principal, dataset, 'first', 'fingerprint', producer)
    ServiceKey.objects.filter(pk=key.pk).update(revoked_at=timezone.now())
    for request_id in ('first', 'new-request'):
        with pytest.raises(Problem):
            deliver(principal, dataset, request_id, 'fingerprint', producer)


def test_source_restricted_key_cannot_download_full_browser_export(example):
    principal, dataset, source = example
    seed(source)
    job = create_export(principal, dataset.slug, max_credits=100, request_id='full-browser-export')
    process_page(job.pk)
    key, _ = issue_key(principal.workspace, 'Other source only', ['datasets:read', 'exports:read'], source_slugs=['other-source'])
    with pytest.raises(Problem):
        download(Principal(principal.workspace, 'service', key), job.pk)


@override_settings(MARKET_STRIPE_PRO_PRICE_ID='price_pro', MARKET_STRIPE_OVERAGE_PRICE_ID='price_meter')
def test_paid_renewal_after_failure_uses_new_provider_period(example):
    principal, dataset, source = example
    account = BillingAccount.objects.get(workspace=principal.workspace)
    new_start = datetime(2026, 9, 15, tzinfo=tz.utc)
    new_end = datetime(2026, 10, 15, tzinfo=tz.utc)
    account.status = 'past_due'
    account.period_start = datetime(2026, 8, 15, tzinfo=tz.utc)
    account.period_end = new_start
    account.allowance_start = account.period_start
    account.stripe_customer_id, account.stripe_subscription_id = 'cus_test', 'sub_test'
    account.save()
    api = Mock()
    api.v1.subscriptions.retrieve.return_value = {'customer': 'cus_test', 'livemode': False, 'currency': 'usd', 'status': 'active', 'latest_invoice': {'status': 'paid'}, 'items': {'data': [
        {'quantity': 1, 'price': {'id': 'price_pro'}, 'current_period_start': int(new_start.timestamp()), 'current_period_end': int(new_end.timestamp())},
        {'price': {'id': 'price_meter'}}]}}
    with patch('plane.commerce.stripe_gateway.client', return_value=api), patch('plane.commerce.stripe_gateway.validate_prices'), patch('plane.commerce.stripe_gateway.timezone.now', return_value=new_start+timedelta(days=5)):
        reconcile_subscription(account.pk)
    account.refresh_from_db()
    assert account.allowance_start == new_start


def test_completed_deletion_does_not_starve_live_reconciliation(example):
    from django.core.management import call_command
    from plane.access.models import Identity, Workspace
    principal, dataset, source = example
    existing = BillingAccount.objects.get(workspace=principal.workspace)
    existing.stripe_subscription_id = 'sub_live'
    existing.reconciled_at = timezone.now()
    existing.save()
    dead = Identity.objects.create(subject='user_deleted_queue', active=False, deleted_at=timezone.now())
    dead_workspace = Workspace.objects.create(owner=dead)
    BillingAccount.objects.create(workspace=dead_workspace, stripe_subscription_id='sub_deleted',
        reconciled_at=timezone.now()-timedelta(days=100), cancellation_requested_at=timezone.now()-timedelta(days=100), cancellation_completed_at=timezone.now()-timedelta(days=99))
    with patch('plane.commerce.management.commands.reconcile_billing.reconcile_subscription') as refresh, patch('plane.commerce.management.commands.reconcile_billing.reconcile_meter', return_value=None):
        call_command('reconcile_billing', limit=1)
        refresh.assert_called_once_with(existing.pk)


@pytest.mark.parametrize('waiting_field', ['lease_until', 'next_attempt_at'])
def test_not_due_outbox_does_not_starve_ready_delivery(example, waiting_field):
    from django.core.management import call_command
    from plane.commerce.models import Delivery, MeterOutbox
    principal, dataset, source = example
    start, end = timezone.now()-timedelta(days=1), timezone.now()+timedelta(days=29)
    rows = []
    for n in range(2):
        delivery = Delivery.objects.create(workspace=principal.workspace, dataset_slug=dataset.slug,
            request_id=str(n), fingerprint='f', response={}, records=1, credits=1, overage_credits=1,
            pricing_cents_per_10000=100, period_start=start, period_end=end)
        rows.append(MeterOutbox.objects.create(delivery=delivery, customer_id='cus_queue', event_name='kwip_overage_credits'))
    MeterOutbox.objects.filter(pk=rows[0].pk).update(**{waiting_field: timezone.now()+timedelta(hours=1)})
    with patch('plane.commerce.management.commands.dispatch_usage.dispatch_one', return_value='submitted') as dispatch:
        call_command('dispatch_usage', limit=1)
        dispatch.assert_called_once_with(rows[1].pk)
