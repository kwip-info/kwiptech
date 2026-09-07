from unittest.mock import patch
import pytest
from django.test import Client, RequestFactory
from plane.public.cutover import DESTINATIONS, moved

@pytest.mark.parametrize('source,destination', DESTINATIONS.items())
@pytest.mark.parametrize('method', ['get', 'head'])
def test_known_information_redirects(source, destination, method):
    response = getattr(Client(), method)('/' + source)
    assert response.status_code == 301
    assert response['Location'] == destination

@pytest.mark.django_db
@pytest.mark.parametrize('method', ['post', 'put', 'patch', 'delete', 'options'])
def test_old_inquiries_never_store_or_forward_body(method, django_assert_num_queries):
    with django_assert_num_queries(0):
        response = getattr(Client(enforce_csrf_checks=True), method)('/digest', data='private inquiry', content_type='text/plain')
    assert response.status_code == 410
    assert 'Location' not in response
    assert response.json()['destination'] == 'https://kwip.info/technology/digest/'

def test_moved_does_not_read_payload():
    request = RequestFactory().post('/digest', data=b'private', content_type='text/plain')
    with patch.object(type(request), 'body', property(lambda self: pytest.fail('Read body'))), patch.object(type(request), 'POST', property(lambda self: pytest.fail('Parsed form'))):
        assert moved(request, 'digest').status_code == 410

@pytest.mark.parametrize('path', ['/unknown', '/docs/missing.md', '/docs/raw/../../README.md', '/https://evil.example', '/docs/platform/missing.md'])
def test_unknown_paths_are_not_open_redirects(path):
    assert Client().get(path).status_code == 404

def test_marketplace_landing_and_legacy_crawlers():
    client = Client()
    response = client.get('/')
    assert response.status_code == 200
    assert b"Find the facts." in response.content
    assert b'https://kwip.info/technology/' in response.content
    assert b'id="search-form"' in response.content
    assert b'https://kwip.info/sitemap.xml' in client.get('/robots.txt').content
    assert client.get('/llms.txt')['Location'] == 'https://kwip.info/technology/llms.txt'

def test_trailing_slash_and_query_do_not_change_destination():
    response=Client().get('/digest/?next=https://evil.example')
    assert response['Location']=='https://kwip.info/technology/digest/'
