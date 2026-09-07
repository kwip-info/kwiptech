from datetime import timedelta
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command, CommandError
from django.test import override_settings
from django.utils import timezone
from plane.access.models import DeviceGrant, RateBucket
from plane.catalog.management.commands.run_marketplace_worker import cleanup_access, execute_task

pytestmark = pytest.mark.django_db


@pytest.mark.django_db(transaction=True)
@override_settings(MARKET_BILLING_ENABLED=False)
def test_empty_unconfigured_once_never_calls_provider():
    with patch('plane.catalog.management.commands.run_marketplace_worker.dispatch_one') as dispatch, patch('plane.commerce.stripe_gateway.client') as client:
        output = StringIO()
        call_command('run_marketplace_worker', once=True, stdout=output)
    dispatch.assert_not_called()
    client.assert_not_called()
    assert 'skipped: billing disabled' in output.getvalue()


def test_once_runs_all_tasks_without_sleep():
    with patch('plane.catalog.management.commands.run_marketplace_worker.execute_task', return_value='ok') as execute, patch('plane.catalog.management.commands.run_marketplace_worker.time.sleep') as sleep:
        call_command('run_marketplace_worker', once=True, limit=7, stdout=StringIO())
    assert [c.args for c in execute.call_args_list] == [('exports', 7), ('dispatch', 7), ('reconcile', 7), ('cleanup', 7)]
    sleep.assert_not_called()


def test_failure_does_not_skip_cleanup_or_leak_exception():
    output = StringIO()
    def fail(name, limit):
        if name == 'dispatch':
            raise RuntimeError('provider-secret-must-not-log')
        return 'ok'
    with patch('plane.catalog.management.commands.run_marketplace_worker.execute_task', side_effect=fail) as execute:
        with pytest.raises(CommandError):
            call_command('run_marketplace_worker', once=True, stderr=output, stdout=StringIO())
    assert execute.call_count == 4
    assert 'RuntimeError' in output.getvalue()
    assert 'provider-secret' not in output.getvalue()


def test_access_cleanup_bounded_preserves_live_windows():
    now = timezone.now()
    for i in range(3):
        DeviceGrant.objects.create(device_hash=str(i), user_code=str(i), name='Synthetic', expires_at=now - timedelta(seconds=1))
        RateBucket.objects.create(key=str(i), starts_at=now - timedelta(days=2))
    DeviceGrant.objects.create(device_hash='live', user_code='live', name='Live', expires_at=now + timedelta(minutes=5))
    RateBucket.objects.create(key='live', starts_at=now)
    assert cleanup_access(2) == {'expired_device_grants': 2, 'stale_rate_buckets': 2}
    assert DeviceGrant.objects.count() == RateBucket.objects.count() == 2
    assert DeviceGrant.objects.filter(device_hash='live').exists()
    assert RateBucket.objects.filter(key='live').exists()


@override_settings(MARKET_BILLING_ENABLED=True, MARKET_STRIPE_SECRET_KEY='', MARKET_STRIPE_PRO_PRICE_ID='price_test', MARKET_STRIPE_OVERAGE_PRICE_ID='price_meter')
def test_incomplete_provider_configuration_skips_reconciliation():
    with patch('plane.catalog.management.commands.run_marketplace_worker.call_command') as command:
        assert execute_task('reconcile', 10).startswith('skipped:')
    command.assert_not_called()


@override_settings(MARKET_BILLING_ENABLED=True, MARKET_STRIPE_SECRET_KEY='sk_test_synthetic', MARKET_STRIPE_PRO_PRICE_ID='price_test', MARKET_STRIPE_OVERAGE_PRICE_ID='price_meter')
def test_configured_reconcile_uses_bounded_command():
    with patch('plane.catalog.management.commands.run_marketplace_worker.call_command') as command:
        execute_task('reconcile', 7)
    assert command.call_args.args == ('reconcile_billing',)
    assert command.call_args.kwargs['limit'] == 7


def test_continuous_worker_obeys_cadence():
    # Two loop iterations at identical monotonic time must not rerun any task.
    with patch('plane.catalog.management.commands.run_marketplace_worker.time.monotonic', return_value=100), patch('plane.catalog.management.commands.run_marketplace_worker.time.sleep', side_effect=[None, KeyboardInterrupt]), patch('plane.catalog.management.commands.run_marketplace_worker.execute_task', return_value='ok') as execute:
        with pytest.raises(KeyboardInterrupt):
            call_command('run_marketplace_worker', stdout=StringIO())
    assert execute.call_count == 4


@override_settings(MARKET_BILLING_ENABLED=True, MARKET_STRIPE_SECRET_KEY='sk_test_synthetic', MARKET_STRIPE_PRO_PRICE_ID='price_test', MARKET_STRIPE_OVERAGE_PRICE_ID='price_meter')
def test_dispatch_only_due_items_and_bounded():
    from plane.access.models import Identity, Workspace
    from plane.commerce.models import Delivery, MeterOutbox
    workspace = Workspace.objects.create(owner=Identity.objects.create(subject='user_worker'))
    now = timezone.now()
    ids = []
    for i, state in enumerate([{}, {}, {'status': 'review'}, {'lease_until': now + timedelta(minutes=2)}, {'next_attempt_at': now + timedelta(minutes=2)}]):
        delivery = Delivery.objects.create(workspace=workspace, dataset_slug='synthetic', request_id=str(i), fingerprint=str(i), response={}, records=1, credits=1, overage_credits=1, pricing_cents_per_10000=100, period_start=now - timedelta(days=1), period_end=now + timedelta(days=1))
        row = MeterOutbox.objects.create(delivery=delivery, customer_id='cus_synthetic', event_name='synthetic', **state)
        ids.append(row.pk)
    with patch('plane.catalog.management.commands.run_marketplace_worker.dispatch_one', return_value='submitted') as dispatch:
        assert execute_task('dispatch', 1) == "{'submitted': 1}"
        assert dispatch.call_args.args == (ids[0],)
    with patch('plane.catalog.management.commands.run_marketplace_worker.dispatch_one', return_value='submitted') as dispatch:
        execute_task('dispatch', 10)
        assert [call.args[0] for call in dispatch.call_args_list] == ids[:2]


def test_failing_export_does_not_starve_selected_peers():
    with patch('plane.catalog.management.commands.run_marketplace_worker.ExportJob.objects') as manager, patch('plane.catalog.management.commands.run_marketplace_worker.process_page', side_effect=[RuntimeError('failure'), None]) as process:
        manager.filter.return_value.order_by.return_value.values_list.return_value.__getitem__.return_value = ['first', 'second']
        with pytest.raises(CommandError):
            execute_task('exports', 2)
    assert [call.args for call in process.call_args_list] == [('first',), ('second',)]
