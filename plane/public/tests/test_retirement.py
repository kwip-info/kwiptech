from unittest.mock import patch

import pytest
from django.test import Client, RequestFactory
from plane.retired import retired

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize('path', ['/v1/sync/batch', '/v1/sync/verify', '/v1/keys/create', '/v1/usage', '/dashboard/', '/dashboard/billing', '/webhooks/clerk', '/webhooks/stripe/', '/sign-up', '/sign-in/factor-one'])
@pytest.mark.parametrize('method', ['get', 'post', 'put', 'delete', 'options'])
def test_retired_routes_never_touch_database(path, method, django_assert_num_queries):
    client = Client(enforce_csrf_checks=True)
    with django_assert_num_queries(0):
        response = getattr(client, method)(path, data='not valid JSON', content_type='application/json') if method != 'get' else client.get(path)
    assert response.status_code == 410
    assert response.json()['error'] == 'hosted_pyscoped_retired'


def test_retirement_does_not_read_body():
    request = RequestFactory().post('/v1/sync/batch', data=b'secret', content_type='application/octet-stream')
    with patch.object(type(request), 'body', property(lambda self: pytest.fail('Retirement read the body'))):
        assert retired(request).status_code == 410


@pytest.mark.parametrize('path', ['/', '/pricing', '/status', '/security', '/terms', '/privacy', '/cookies', '/docs', '/docs/adoption.md', '/docs/raw/guarantees.md', '/docs/manifest.json', '/healthz', '/v1/ping'])
def test_public_routes_do_not_require_database(path, django_assert_num_queries):
    with django_assert_num_queries(0):
        response = Client().get(path)
    assert response.status_code == 200


@pytest.mark.parametrize('path', ['/docs/raw//etc/passwd.md', '/docs/raw/%2e%2e/README.md', '/docs/platform/raw//etc/passwd.md'])
def test_document_paths_cannot_escape_bundle(path):
    assert Client().get(path).status_code == 404
