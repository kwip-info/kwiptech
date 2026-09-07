"""Provider provisioning is explicit, resumable and separate from customer billing."""
import copy
import io
import json
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import stripe
from django.core.management import call_command
from django.core.management.base import CommandError

from plane.commerce.management.commands import configure_marketplace_billing as setup


class Service:
    def __init__(self, kind):
        self.kind, self.objects, self.creates = kind, [], []
        self.fail_after_create = False

    def list(self, params=None):
        data = self.objects
        if params and 'lookup_keys' in params:
            data = [x for x in data if x.get('lookup_key') in params['lookup_keys']]
        # Stripe does not return the create-only endpoint secret on list/retrieve.
        return {'data': [{k: copy.deepcopy(v) for k, v in x.items() if k != 'secret'} for x in data], 'has_more': False}

    def retrieve(self, id):
        found = next((x for x in self.objects if x['id'] == id), None)
        if not found:
            raise stripe.InvalidRequestError('not present', 'id', code='resource_missing', http_status=404)
        return copy.deepcopy(found)

    def create(self, params, options=None):
        self.creates.append((copy.deepcopy(params), copy.deepcopy(options)))
        assert options['idempotency_key'].startswith('kwip-marketplace-setup-v1-')
        result = copy.deepcopy(params)
        result.update(id=params.get('id', f'{self.kind}_{len(self.objects) + 1}'), livemode=False)
        if self.kind in ('prod', 'price'):
            result['active'] = True
        if self.kind == 'mtr':
            result['status'] = 'active'
        if self.kind == 'we':
            result.update(status='enabled', secret='whsec_private_mock_value')
        self.objects.append(result)
        if self.fail_after_create:
            self.fail_after_create = False
            raise stripe.APIConnectionError('sensitive provider error must not print')
        return copy.deepcopy(result)


@pytest.fixture
def api(settings):
    settings.MARKET_ORIGIN = 'https://kwip.tech'
    settings.MARKET_STRIPE_LIVEMODE = False
    settings.MARKET_PRO_MONTHLY_CENTS = 2900
    settings.MARKET_OVERAGE_CENTS_PER_10000 = 100
    settings.MARKET_STRIPE_METER_EVENT = 'kwip_overage_credits'
    return SimpleNamespace(v1=SimpleNamespace(
        products=Service('prod'), prices=Service('price'),
        billing=SimpleNamespace(meters=Service('mtr')),
        webhook_endpoints=Service('we'),
        accounts=SimpleNamespace(retrieve_current=lambda: {'id': 'acct_test'}),
    ))


def apply(api, target, **kwargs):
    out = io.StringIO()
    with patch.object(setup, 'client', return_value=api):
        call_command('configure_marketplace_billing', apply=True, output=str(target), stdout=out, **kwargs)
    return out.getvalue()


def creates(api):
    return sum(len(s.creates) for s in (api.v1.products, api.v1.prices, api.v1.billing.meters, api.v1.webhook_endpoints))


def test_default_dry_run_is_offline_no_credentials_or_file_required(api, tmp_path):
    output = io.StringIO()
    target = tmp_path / 'never-created.json'
    with patch.object(setup, 'client', side_effect=AssertionError('offline preview must not connect')):
        call_command('configure_marketplace_billing', output=str(target), stdout=output)
    data = json.loads(output.getvalue())
    assert data['mode'] == 'offline_dry_run'
    assert data['existing_provider_objects_checked'] is False
    assert data['intent']['overage_unit_amount_decimal'] == '0.01'
    assert data['intent']['webhook_url'] == 'https://kwip.tech/integrations/stripe'
    assert data['intent']['billing_enabled'] is False
    assert not target.exists()


def test_apply_requires_private_output_before_connecting(api):
    with patch.object(setup, 'client', side_effect=AssertionError('must validate output first')):
        with pytest.raises(CommandError, match='requires --output'):
            call_command('configure_marketplace_billing', apply=True)


def test_creates_new_objects_then_reuses_without_touching_legacy(api, tmp_path):
    legacy = {'id': 'prod_old', 'name': 'Old PyScoped', 'active': True, 'livemode': False, 'metadata': {}}
    api.v1.products.objects.append(legacy)
    target = tmp_path / 'setup.json'
    text = apply(api, target)
    first = json.loads(target.read_text())
    assert creates(api) == 5
    assert first['status'] == 'configured_requires_uat'
    assert first['ready_for_sales'] is False
    assert first['config']['MARKET_BILLING_ENABLED'] is False
    assert first['config']['MARKET_STRIPE_WEBHOOK_SECRET'] == 'whsec_private_mock_value'
    assert os.stat(target).st_mode & 0o777 == 0o600
    assert 'whsec_' not in text
    assert 'sk_' not in target.read_text()
    apply(api, target)
    assert creates(api) == 5
    assert api.v1.products.objects[0] == legacy
    price = api.v1.prices.objects[1]
    assert price['unit_amount_decimal'] == '0.01'
    assert price['recurring'] == {'interval': 'month', 'usage_type': 'metered', 'meter': 'mtr_1'}
    assert 'tiers' not in price and 'transform_quantity' not in price
    meter = api.v1.billing.meters.objects[0]
    assert meter['customer_mapping']['event_payload_key'] == 'stripe_customer_id'
    assert meter['value_settings']['event_payload_key'] == 'value'
    assert meter['default_aggregation'] == {'formula': 'sum'}
    assert api.v1.webhook_endpoints.objects[0]['enabled_events'] == setup.EVENTS


def test_existing_incompatible_price_refused_before_any_new_object(api, tmp_path):
    target = tmp_path / 'setup.json'
    apply(api, target)
    api.v1.prices.objects[0]['unit_amount'] = 9999
    before = creates(api)
    with pytest.raises(CommandError, match='fixed price differs'):
        apply(api, target)
    assert creates(api) == before


def test_other_app_product_is_not_adopted(api, tmp_path):
    api.v1.products.objects.append({'id': setup.PRODUCT_ID, 'name': 'Old product', 'livemode': False, 'active': True, 'metadata': {}})
    with pytest.raises(CommandError, match='not owned'):
        apply(api, tmp_path / 'setup.json')
    assert creates(api) == 0


def test_mismatched_mode_meter_mapping_and_duplicate_endpoint_fail_closed(api, tmp_path):
    target = tmp_path / 'setup.json'
    apply(api, target)
    api.v1.billing.meters.objects[0]['customer_mapping']['event_payload_key'] = 'other_customer'
    with pytest.raises(CommandError, match='meter configuration differs'):
        apply(api, target)
    api.v1.billing.meters.objects[0]['customer_mapping']['event_payload_key'] = 'stripe_customer_id'
    api.v1.products.objects[0]['livemode'] = True
    with pytest.raises(CommandError, match='different mode'):
        apply(api, target)
    api.v1.products.objects[0]['livemode'] = False
    api.v1.webhook_endpoints.objects.append(dict(api.v1.webhook_endpoints.objects[0], id='we_duplicate'))
    with pytest.raises(CommandError, match='Multiple matching webhook'):
        apply(api, target)
    assert creates(api) == 5


def test_partial_remote_failure_resumes_without_duplicate_objects(api, tmp_path):
    api.v1.billing.meters.fail_after_create = True
    target = tmp_path / 'setup.json'
    with pytest.raises(CommandError, match='could not complete') as err:
        apply(api, target)
    assert 'sensitive provider error' not in str(err.value)
    state = json.loads(target.read_text())
    assert state['objects']['product_id'] == setup.PRODUCT_ID
    assert len(api.v1.billing.meters.objects) == 1
    apply(api, target)
    assert creates(api) == 5
    assert json.loads(target.read_text())['status'] == 'configured_requires_uat'


def test_ambiguous_webhook_creation_requires_secret_recovery_not_duplicate(api, tmp_path, monkeypatch):
    api.v1.webhook_endpoints.fail_after_create = True
    target = tmp_path / 'setup.json'
    with pytest.raises(CommandError):
        apply(api, target)
    with pytest.raises(CommandError, match='secret is not recoverable'):
        apply(api, target)
    assert len(api.v1.webhook_endpoints.objects) == 1
    monkeypatch.setenv('KWIP_RECOVERED_SECRET', 'whsec_recovered_privately')
    text = apply(api, target, existing_webhook_secret_env='KWIP_RECOVERED_SECRET')
    assert len(api.v1.webhook_endpoints.objects) == 1
    assert 'whsec_' not in text
    assert json.loads(target.read_text())['config']['MARKET_STRIPE_WEBHOOK_SECRET'] == 'whsec_recovered_privately'


def test_matching_webhook_without_journal_secret_cannot_be_automatically_recreated(api, tmp_path):
    apply(api, tmp_path / 'original.json')
    with pytest.raises(CommandError, match='secret is not recoverable'):
        apply(api, tmp_path / 'new-file.json')
    assert creates(api) == 5


def test_journal_cannot_move_accounts_or_change_pricing(api, tmp_path, settings):
    target = tmp_path / 'setup.json'
    apply(api, target)
    api.v1.accounts.retrieve_current = lambda: {'id': 'acct_different'}
    with pytest.raises(CommandError, match='another account'):
        apply(api, target)
    api.v1.accounts.retrieve_current = lambda: {'id': 'acct_test'}
    settings.MARKET_PRO_MONTHLY_CENTS = 3900
    with pytest.raises(CommandError, match='another account'):
        apply(api, target)
    assert creates(api) == 5


def test_output_rejects_repository_symlink_hardlink_and_public_permissions(api, tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    (repo / '.git').mkdir()
    with pytest.raises(CommandError, match='outside every Git'):
        apply(api, repo / 'secret.json')
    target = tmp_path / 'public.json'
    target.write_text('{}')
    target.chmod(0o644)
    with pytest.raises(CommandError, match='0600'):
        apply(api, target)
    target.chmod(0o600)
    alias = tmp_path / 'symlink.json'
    alias.symlink_to(target)
    with pytest.raises(CommandError, match='securely open'):
        apply(api, alias)
    hardlink = tmp_path / 'hardlink.json'
    os.link(target, hardlink)
    with pytest.raises(CommandError, match='hard links'):
        apply(api, hardlink)
    assert creates(api) == 0


def test_repeated_pagination_cursor_refuses_incomplete_discovery():
    service = SimpleNamespace(list=lambda params: {'data': [{'id': 'same'}], 'has_more': True})
    with pytest.raises(CommandError, match='pagination is incomplete'):
        setup.rows(service)


def test_dry_run_rejects_unsafe_origin_and_amounts(settings):
    settings.MARKET_ORIGIN = 'https://user:secret@example.com'
    with pytest.raises(CommandError, match='HTTPS origin'):
        call_command('configure_marketplace_billing')
    settings.MARKET_ORIGIN = 'https://example.com'
    settings.MARKET_OVERAGE_CENTS_PER_10000 = 0
    with pytest.raises(CommandError, match='positive bounded'):
        call_command('configure_marketplace_billing')
