"""Full routed marketplace contracts with real service-key authentication.

Only the external Clerk session assertion is replaced; catalog, authorization,
billing, persistence, routes and error adapters run normally.
"""
import json
from unittest.mock import patch

import pytest
from django.test import Client, override_settings
from plane.access.auth import issue_key
from plane.access.models import Identity, Workspace
from plane.catalog.models import Dataset, Source, Record, RecordVersion, IngestionBatch
from plane.catalog.services import register_dataset, register_source, ingest_batch
from plane.commerce.models import Delivery

pytestmark = pytest.mark.django_db


def post(client, path, payload, key='request-0001'):
    return client.post(path, json.dumps(payload), content_type='application/json', HTTP_IDEMPOTENCY_KEY=key)


def dataset_manifest():
    return {'slug': 'synthetic-api', 'title': 'Synthetic API', 'schema_version': 1, 'credits_per_record': 2,
            'fields': {'title': {'type': 'string', 'required': True}, 'amount': {'type': 'integer'}, 'active': {'type': 'boolean'}}}


def source_manifest(slug='example', rights='approved'):
    return {'slug': slug, 'name': 'Synthetic example', 'url': 'https://example.com/data', 'schema_version': 1,
            'rights_status': rights, 'attribution': 'Synthetic test only', 'license_url': 'https://example.com/license'}


def item(identity='a', title='Visible'):
    return {'external_id': identity, 'payload': {'title': title, 'amount': 5, 'active': True}, 'observed_at': '2026-01-01T00:00:00Z'}


@pytest.fixture
def operator():
    identity = Identity.objects.create(subject='user_market_operator', is_operator=True)
    workspace = Workspace.objects.create(owner=identity)
    with patch('plane.access.auth.verify_session', return_value={'sub': identity.subject}):
        yield workspace, Client(HTTP_AUTHORIZATION='Bearer synthetic-external-clerk-session')


@pytest.fixture
def customer():
    workspace = Workspace.objects.create(owner=Identity.objects.create(subject='user_market_customer'))
    key, token = issue_key(workspace, 'Read client', ['datasets:read'])
    return workspace, key, Client(HTTP_AUTHORIZATION='Bearer ' + token)


@pytest.fixture
def populated():
    dataset = register_dataset(dataset_manifest())
    source = register_source(dataset, source_manifest())
    ingest_batch(source, [item(), item('b')], 'synthetic-seed')
    dataset.status = 'published'
    dataset.save()
    return dataset, source


def test_empty_catalog_and_checkout_blocked(operator):
    _, browser = operator
    public = Client()
    assert public.get('/api/v2/datasets').json() == {'datasets': [], 'next_after': None}
    plans = public.get('/api/v2/plans').json()
    assert plans['catalog_has_data'] is False
    assert plans['purchases_available'] is False
    with override_settings(MARKET_BILLING_ENABLED=True):
        response = post(browser, '/api/v2/billing/checkout', {})
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'catalog_empty'
    assert not Delivery.objects.exists()
    assert not Dataset.objects.exists()


def test_draft_and_unapproved_sources_are_not_public():
    dataset = register_dataset(dataset_manifest())
    source = register_source(dataset, source_manifest(rights='pending'))
    client = Client()
    assert client.get('/api/v2/datasets').json()['datasets'] == []
    assert client.get('/api/v2/datasets/' + dataset.slug).status_code == 404
    dataset.status = 'published'
    dataset.save()  # Simulate invalid/operator-bypassed publication; route still gates rights.
    assert client.get('/api/v2/datasets').json()['datasets'] == []
    source.rights_status = 'approved'
    source.save()
    assert len(client.get('/api/v2/datasets').json()['datasets']) == 1
    source.active = False
    source.save()
    assert client.get('/api/v2/datasets/' + dataset.slug).status_code == 404


def test_operator_registration_ingestion_flow(operator):
    workspace, browser = operator
    route = '/api/v2/operator/datasets'
    assert post(browser, route, {'dataset': dataset_manifest()}).json()['dry_run'] is True
    assert not Dataset.objects.exists()
    assert post(browser, route, {'dataset': dataset_manifest(), 'dry_run': False}).status_code == 200
    sources = route + '/synthetic-api/sources'
    assert post(browser, sources, {'source': source_manifest()}).status_code == 200
    assert not Source.objects.exists()
    assert post(browser, sources, {'source': source_manifest(), 'dry_run': False}).status_code == 200
    _, token = issue_key(workspace, 'Scoped publisher', ['ingest:write'], dataset_slugs=['synthetic-api'], source_slugs=['example'])
    publisher = Client(HTTP_AUTHORIZATION='Bearer ' + token)
    batches = sources + '/example/batches'
    assert post(publisher, batches, {'items': [item()]}).json()['validated'] == 1
    assert not Record.objects.exists()
    applied = post(publisher, batches, {'items': [item()], 'dry_run': False})
    assert applied.status_code == 200
    assert post(publisher, batches, {'items': [item()], 'dry_run': False}).json()['replayed'] is True
    assert post(publisher, batches, {'items': [item(title='Different')], 'dry_run': False}).status_code == 400
    assert IngestionBatch.objects.count() == RecordVersion.objects.count() == 1
    assert post(publisher, route, {'dataset': dataset_manifest()}).status_code == 403
    assert post(publisher, sources + '/other/batches', {'items': [item()]}).status_code == 403
    assert post(browser, route, {'dataset': dataset_manifest() | {'status': 'published'}, 'dry_run': False}).status_code == 200
    assert Client().get('/api/v2/datasets/synthetic-api').json()['sources'][0]['slug'] == 'example'


def test_customer_cannot_publish_or_read_without_scope(customer, populated):
    workspace, _, client = customer
    assert post(client, '/api/v2/operator/datasets', {'dataset': dataset_manifest()}).status_code == 403
    _, token = issue_key(workspace, 'Wrong dataset', ['datasets:read'], dataset_slugs=['other'])
    other = Client(HTTP_AUTHORIZATION='Bearer ' + token)
    assert post(other, '/api/v2/datasets/synthetic-api/query', {}).status_code == 403
    _, token = issue_key(workspace, 'Export scope only', ['exports:read'])
    wrong_scope = Client(HTTP_AUTHORIZATION='Bearer ' + token)
    assert post(wrong_scope, '/api/v2/datasets/synthetic-api/query', {}).status_code == 403
    assert post(Client(), '/api/v2/datasets/synthetic-api/query', {}).status_code == 401


def test_query_projection_budget_and_exact_replay(customer, populated):
    _, _, client = customer
    route = '/api/v2/datasets/synthetic-api/query'
    query = {'filters': {'amount': 5, 'active': True}, 'fields': ['title'], 'limit': 1, 'max_credits': 2}
    first = post(client, route, query)
    assert first.status_code == 200
    result = first.json()
    assert result['records'][0]['data'] == {'title': 'Visible'}
    assert result['usage']['credits'] == 2
    assert result['next_cursor']
    assert post(client, route, query).json() == result
    assert Delivery.objects.count() == 1
    assert post(client, route, query | {'limit': 2}).status_code == 409
    assert post(client, route, query | {'max_credits': 1}, key='request-0002').status_code == 402
    assert Delivery.objects.count() == 1
    assert first['Cache-Control'] == 'no-store'


@pytest.mark.parametrize('query', [{'filters': {'amount': '5'}}, {'filters': {'active': 1}}, {'filters': {'title__contains': 'x'}}, {'fields': [['title']]}, {'limit': True}, {'cursor': []}, {'extra': True}, {'max_credits': -1}])
def test_query_malformed_inputs_do_not_create_delivery(customer, populated, query):
    response = post(customer[2], '/api/v2/datasets/synthetic-api/query', query)
    assert response.status_code == 400
    assert not Delivery.objects.exists()


def test_strict_json_and_idempotency_boundary(customer, populated):
    client = customer[2]
    route = '/api/v2/datasets/synthetic-api/query'
    assert client.post(route, data='{}', content_type='text/plain').status_code == 415
    assert client.post(route, data='[1]', content_type='application/json').status_code == 400
    assert client.post(route, data='{"limit":NaN}', content_type='application/json').status_code == 400
    assert post(client, route, {}, key='short').status_code == 400
    assert not Delivery.objects.exists()


@pytest.mark.parametrize('route', ['/v1/records', '/v1/sync', '/dashboard/new', '/webhooks/stripe', '/sign-up'])
def test_retired_routes_never_ingest(customer, route):
    before = (Record.objects.count(), IngestionBatch.objects.count(), Delivery.objects.count())
    response = customer[2].post(route, data='not-json', content_type='application/json')
    assert response.status_code == 410
    assert (Record.objects.count(), IngestionBatch.objects.count(), Delivery.objects.count()) == before


def test_source_scoped_read_key_never_leaks_other_source(customer, populated):
    dataset, _ = populated
    hidden = register_source(dataset, source_manifest('confidential'))
    ingest_batch(hidden, [item('secret', 'Must not leak')], 'hidden-seed')
    _, token = issue_key(customer[0], 'Source-restricted reader', ['datasets:read'], dataset_slugs=[dataset.slug], source_slugs=['example'])
    reader = Client(HTTP_AUTHORIZATION='Bearer ' + token)
    response = post(reader, '/api/v2/datasets/synthetic-api/query', {})
    # Deny or filter is acceptable; returning a different source is not.
    assert response.status_code == 403 or (response.status_code == 200 and all(row['source']['slug'] == 'example' for row in response.json()['records']))


def test_cached_replay_never_leaks_withdrawn_source(customer, populated):
    dataset, source = populated
    other = register_source(dataset, source_manifest('remaining'))
    ingest_batch(other, [item('remaining')], 'remaining-seed')
    route = '/api/v2/datasets/synthetic-api/query'
    first = post(customer[2], route, {})
    assert first.status_code == 200
    source.rights_status = 'blocked'
    source.save()
    replay = post(customer[2], route, {})
    assert replay.status_code in (403, 409, 410) or (replay.status_code == 200 and all(row['source']['slug'] != source.slug for row in replay.json()['records']))


def test_operator_wrapper_unknown_fields_are_rejected(operator):
    _, browser = operator
    route = '/api/v2/operator/datasets'
    response = post(browser, route, {'dataset': dataset_manifest(), 'dry_run': False, 'unexpected': True})
    assert response.status_code == 400
    assert not Dataset.objects.exists()


def test_source_wrapper_unknown_fields_are_rejected(operator):
    _, browser = operator
    dataset = register_dataset(dataset_manifest())
    response = post(browser, '/api/v2/operator/datasets/' + dataset.slug + '/sources', {'source': source_manifest(), 'dry_run': False, 'unexpected': True})
    assert response.status_code == 400
    assert not Source.objects.exists()


def test_malformed_schema_and_atomic_batch_through_http(operator):
    workspace, browser = operator
    route = '/api/v2/operator/datasets'
    invalid = dataset_manifest() | {'fields': {'bad': {'type': []}}}
    assert post(browser, route, {'dataset': invalid, 'dry_run': False}).status_code == 400
    invalid = dataset_manifest() | {'slug': {}}
    assert post(browser, route, {'dataset': invalid, 'dry_run': False}).status_code == 400
    assert not Dataset.objects.exists()
    dataset = register_dataset(dataset_manifest())
    register_source(dataset, source_manifest())
    _, token = issue_key(workspace, 'Publisher', ['ingest:write'], dataset_slugs=[dataset.slug], source_slugs=['example'])
    publisher = Client(HTTP_AUTHORIZATION='Bearer ' + token)
    batch_route = '/api/v2/operator/datasets/' + dataset.slug + '/sources/example/batches'
    invalid_item = item('bad') | {'payload': {'amount': 'wrong'}}
    assert post(publisher, batch_route, {'items': [item(), invalid_item], 'dry_run': False}).status_code == 400
    assert not Record.objects.exists()
    assert not IngestionBatch.objects.exists()


def test_idempotency_receipts_are_workspace_scoped(customer, populated):
    route = '/api/v2/datasets/synthetic-api/query'
    first = post(customer[2], route, {'limit': 1})
    other_workspace = Workspace.objects.create(owner=Identity.objects.create(subject='user_other_market'))
    _, token = issue_key(other_workspace, 'Other reader', ['datasets:read'])
    other = Client(HTTP_AUTHORIZATION='Bearer ' + token)
    second = post(other, route, {'limit': 1})
    assert first.status_code == second.status_code == 200
    assert first.json()['usage']['receipt_id'] != second.json()['usage']['receipt_id']
    assert Delivery.objects.filter(workspace=customer[0]).count() == 1
    assert Delivery.objects.filter(workspace=other_workspace).count() == 1


def test_revoked_key_cannot_replay_cached_delivery(customer, populated):
    from django.utils import timezone
    workspace, key, client = customer
    route = '/api/v2/datasets/synthetic-api/query'
    assert post(client, route, {}).status_code == 200
    key.revoked_at = timezone.now()
    key.save()
    assert post(client, route, {}).status_code == 401
    assert Delivery.objects.filter(workspace=workspace).count() == 1


@pytest.mark.parametrize('change', ['revoked', 'scopes', 'source_restriction'])
def test_ingest_rechecks_stale_principal_at_write_boundary(operator, change):
    from django.utils import timezone
    from plane.access.auth import Principal
    from plane.access.models import ServiceKey
    workspace, _ = operator
    dataset = register_dataset(dataset_manifest())
    register_source(dataset, source_manifest())
    key, _ = issue_key(workspace, 'Publisher', ['ingest:write'], dataset_slugs=[dataset.slug], source_slugs=['example'])
    stale = Principal(workspace, 'service', key)
    changes = {'revoked': {'revoked_at': timezone.now()}, 'scopes': {'scopes': ['datasets:read']}, 'source_restriction': {'source_slugs': ['different']}}
    ServiceKey.objects.filter(pk=key.pk).update(**changes[change])
    # Reproduce authentication completing before a concurrent revocation/change.
    # Everything after authentication (real route, locks, authorization, ingestion)
    # remains real; the injected Principal intentionally contains stale objects.
    with patch('plane.access.http.authenticate', return_value=stale):
        response = post(Client(), '/api/v2/operator/datasets/' + dataset.slug + '/sources/example/batches', {'items': [item()], 'dry_run': False})
    assert response.status_code in (401, 403)
    assert not Record.objects.exists()
    assert not IngestionBatch.objects.exists()


@pytest.mark.parametrize('change', ['deleted', 'operator_removed'])
@pytest.mark.parametrize('resource', ['dataset', 'source'])
def test_registration_rechecks_stale_operator_at_write_boundary(operator, change, resource):
    from django.utils import timezone
    from plane.access.auth import Principal
    workspace, _ = operator
    stale = Principal(workspace, 'session')
    assert stale.workspace.owner.is_operator
    if resource == 'dataset':
        route = '/api/v2/operator/datasets'
        payload = {'dataset': dataset_manifest(), 'dry_run': False}
    else:
        dataset = register_dataset(dataset_manifest())
        route = '/api/v2/operator/datasets/' + dataset.slug + '/sources'
        payload = {'source': source_manifest(), 'dry_run': False}
    before = (Dataset.objects.count(), Source.objects.count())
    values = {'deleted_at': timezone.now()} if change == 'deleted' else {'is_operator': False}
    Identity.objects.filter(pk=workspace.owner_id).update(**values)
    with patch('plane.access.http.authenticate', return_value=stale):
        response = post(Client(), route, payload)
    assert response.status_code == 403
    assert (Dataset.objects.count(), Source.objects.count()) == before
