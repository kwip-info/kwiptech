"""Guard public discovery, route drift and the safety-critical agent contract."""
import json
import re

import pytest
from django.test import RequestFactory
from django.urls import resolve

from plane.market import discovery


def test_discovery_is_public_static_and_contains_no_provider_configuration(settings):
    settings.MARKET_STRIPE_SECRET_KEY = 'must-not-appear-stripe-secret'
    settings.MARKET_CLERK_PUBLIC_KEY = 'must-not-appear-clerk-config'
    settings.MARKET_ORIGIN = 'https://must-not-appear.example'
    # No db marker: discovery must not read account/usage/data tables.
    response = discovery.openapi(RequestFactory().get('/api/v2/openapi.json'))
    assert response.status_code == 200
    spec = json.loads(response.content)
    assert spec['openapi'] == '3.1.0'
    assert spec['servers'] == [{'url': '/', 'description': 'Same origin as the served specification; production https://kwip.tech.'}]
    assert b'must-not-appear' not in response.content
    assert response['X-Content-Type-Options'] == 'nosniff'
    assert response['Cache-Control'] == 'public, max-age=300'


def test_agent_guide_is_plain_text_and_read_only():
    factory = RequestFactory()
    response = discovery.agents(factory.get('/agents.txt'))
    assert response.status_code == 200
    assert response['Content-Type'] == 'text/plain; charset=utf-8'
    assert b'/api/v2/openapi.json' in response.content
    assert b'not OAuth' in response.content
    for view in (discovery.agents, discovery.openapi):
        assert view(factory.head('/')).status_code == 200
        assert view(factory.post('/')).status_code == 405


def test_every_specification_operation_resolves_and_has_unique_identity():
    spec = discovery.specification()
    identities = []
    for path, operations in spec['paths'].items():
        route = re.sub(r'\{(?:key_id|job_id)\}', '00000000-0000-0000-0000-000000000001', path)
        route = re.sub(r'\{\w+\}', 'synthetic', route)
        match = resolve(route)
        assert match.func.__module__.startswith('plane.')
        for method, operation in operations.items():
            assert method in ('get', 'post', 'delete')
            identities.append(operation['operationId'])
            assert operation['responses']
            parameters = operation.get('parameters', [])
            assert set(re.findall(r'\{(\w+)\}', path)) == {
                p['name'] for p in parameters if p['in'] == 'path' and p['required']
            }
    assert len(identities) == len(set(identities))


def test_all_schema_references_resolve():
    spec = discovery.specification()

    def walk(value):
        if isinstance(value, dict):
            if '$ref' in value:
                assert value['$ref'].startswith('#/')
                current = spec
                for key in value['$ref'][2:].split('/'):
                    current = current[key]
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(spec)


def assert_required_shape(value, schema, definitions):
    """Check documented required response fields, including nested arrays/objects."""
    if '$ref' in schema:
        return assert_required_shape(value, definitions[schema['$ref'].rsplit('/', 1)[-1]], definitions)
    for part in schema.get('allOf', []):
        assert_required_shape(value, part, definitions)
    if schema.get('type') == 'object':
        assert isinstance(value, dict)
        assert set(schema.get('required', [])) <= set(value)
        for key, child in schema.get('properties', {}).items():
            if key in value:
                assert_required_shape(value[key], child, definitions)
    elif schema.get('type') == 'array':
        assert isinstance(value, list)
        for child in value:
            assert_required_shape(child, schema['items'], definitions)


@pytest.mark.django_db
def test_public_responses_match_documented_required_fields(client):
    spec = discovery.specification()
    for url in ('/api/v2/datasets', '/api/v2/plans'):
        response = client.get(url)
        assert response.status_code == 200
        assert response['Cache-Control'] == 'no-store'
        schema = spec['paths'][url]['get']['responses']['200']['content']['application/json']['schema']
        assert_required_shape(response.json(), schema, spec['components']['schemas'])
    assert client.get('/api/v2/datasets').json() == {'datasets': [], 'next_after': None}
    assert client.get('/api/v2/plans').json()['purchases_available'] is False


@pytest.mark.django_db
def test_documented_private_operations_require_bearer_authentication(client):
    for path, operations in discovery.specification()['paths'].items():
        route = re.sub(r'\{(?:key_id|job_id)\}', '00000000-0000-0000-0000-000000000001', path)
        route = re.sub(r'\{\w+\}', 'synthetic', route)
        for method, operation in operations.items():
            if operation['security']:
                response = getattr(client, method)(route, data='{}', content_type='application/json') if method != 'get' else client.get(route)
                assert response.status_code == 401, (method, path, response.content)
                assert response.json()['error']['code'] == 'authentication_required'
                assert response['WWW-Authenticate'] == 'Bearer'


def test_scope_and_browser_boundaries_are_explicit():
    spec = discovery.specification()
    browser_only = {
        '/api/v2/keys', '/api/v2/keys/{key_id}', '/api/v2/device/approve',
        '/api/v2/billing/checkout', '/api/v2/billing/portal', '/api/v2/billing/overage',
        '/api/v2/operator/datasets', '/api/v2/operator/datasets/{slug}/sources',
    }
    for path in browser_only:
        for operation in spec['paths'][path].values():
            assert operation['security'] == [{'BrowserSession': []}]
    schemes = spec['components']['securitySchemes']
    assert {scheme['type'] for scheme in schemes.values()} == {'http'}
    assert all('flows' not in scheme for scheme in schemes.values())
    for name in ('device/start', 'device/poll'):
        assert spec['paths']['/api/v2/' + name]['post']['security'] == []
    query = spec['paths']['/api/v2/datasets/{slug}/query']['post']
    assert query['parameters'][-1]['schema']['minLength'] == 8
    assert {'402', '409', '410'} <= set(query['responses'])
    ingest = spec['paths']['/api/v2/operator/datasets/{slug}/sources/{source_slug}/batches']['post']
    assert '400' in ingest['responses']
    assert 'NOT 409' in ingest['description']
    exports = spec['paths']['/api/v2/exports']['post']
    assert '202' in exports['responses']
    assert 'even if never downloaded' in exports['description']


def test_spec_file_is_portable_and_guide_points_to_existing_local_contracts():
    spec = json.loads((discovery.DOCUMENTS / 'openapi.json').read_text())
    assert spec == discovery.specification()
    guide = (discovery.DOCUMENTS / 'AGENT_GUIDE.md').read_text()
    for name in ('DATA_CONTRACT.md', 'EXPORT_CONTRACT.md', 'BILLING_CONTRACT.md', 'OPERATIONS.md'):
        assert (discovery.DOCUMENTS / name).is_file()
        assert name in guide
    assert not any(term in guide for term in ('sk_live_', 'sk_test_', 'pk_live_', 'pk_test_'))
