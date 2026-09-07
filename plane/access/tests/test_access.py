import json
from datetime import timedelta
from unittest.mock import patch
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from django.test import Client, override_settings
from django.utils import timezone
from plane.access.auth import issue_key, verify_session
from plane.access.errors import Problem
from plane.access.models import Identity, Workspace, ServiceKey, DeviceGrant

pytestmark = pytest.mark.django_db

@pytest.fixture
def workspace():
    return Workspace.objects.create(owner=Identity.objects.create(subject='user_test'))

@pytest.fixture
def browser(workspace):
    with patch('plane.access.auth.verify_session', return_value={'sub': workspace.owner.subject}):
        yield Client(HTTP_AUTHORIZATION='Bearer synthetic-browser-token')

def post(client, path, data):
    return client.post('/api/v2/' + path, data=json.dumps(data), content_type='application/json')

def test_keys_are_hashed_scoped_revocable_and_not_disclosed(browser, workspace):
    result = post(browser, 'keys', {'name': 'Research agent', 'scopes': ['datasets:read']})
    assert result.status_code == 200
    token = result.json()['token']
    key = ServiceKey.objects.get()
    assert token not in key.token_hash and key.prefix != token
    service = Client(HTTP_AUTHORIZATION='Bearer ' + token)
    assert service.get('/api/v2/account').status_code == 200
    assert service.get('/api/v2/keys').status_code == 403
    assert token not in browser.get('/api/v2/keys').content.decode()
    assert browser.delete('/api/v2/keys/' + str(key.pk)).status_code == 200
    assert service.get('/api/v2/account').status_code == 401

def test_cross_account_revocation_is_hidden(browser):
    other = Workspace.objects.create(owner=Identity.objects.create(subject='user_other'))
    key, token = issue_key(other, 'Other key', ['datasets:read'])
    assert browser.delete('/api/v2/keys/' + str(key.pk)).status_code == 404
    assert Client(HTTP_AUTHORIZATION='Bearer ' + token).get('/api/v2/account').status_code == 200

def test_operator_scope_and_invalid_requests(browser):
    assert post(browser, 'keys', {'name': 'Bad publisher', 'scopes': ['ingest:write']}).status_code == 403
    for values in [{'name': '', 'scopes': ['datasets:read']}, {'name': 'Bad', 'scopes': [[]]}, {'name': 'Bad', 'scopes': ['datasets:read'], 'days': True}]:
        assert post(browser, 'keys', values).status_code == 400
    assert Client().get('/api/v2/keys').status_code == 401
    assert browser.post('/api/v2/keys', data='{}', content_type='text/plain').status_code == 415

def test_disabled_identity_and_expiry(workspace):
    key, token = issue_key(workspace, 'Agent', ['datasets:read'])
    client = Client(HTTP_AUTHORIZATION='Bearer ' + token)
    workspace.owner.active = False
    workspace.owner.save()
    assert client.get('/api/v2/account').status_code == 401
    workspace.owner.active = True
    workspace.owner.save()
    key.expires_at = timezone.now() - timedelta(seconds=1)
    key.save()
    assert client.get('/api/v2/account').status_code == 401

def test_device_link_requires_explicit_approval_and_one_time_exchange(browser):
    agent = Client()
    start = post(agent, 'device/start', {'name': 'My agent'}).json()
    poll = {'device_code': start['device_code']}
    assert post(agent, 'device/poll', poll).json()['error']['code'] == 'authorization_pending'
    assert post(agent, 'device/poll', poll).status_code == 429
    assert browser.get('/api/v2/device/approve', {'user_code': start['user_code']}).json()['name'] == 'My agent'
    assert post(browser, 'device/approve', {'user_code': start['user_code'], 'decision': 'approve'}).status_code == 200
    DeviceGrant.objects.update(last_poll_at=timezone.now() - timedelta(seconds=6))
    response = post(agent, 'device/poll', poll)
    assert response.status_code == 200
    token = response.json()['access_token']
    assert Client(HTTP_AUTHORIZATION='Bearer ' + token).get('/api/v2/account').status_code == 200
    assert post(agent, 'device/poll', poll).status_code == 400
    assert token not in str(DeviceGrant.objects.values().get())

def test_device_denial_and_expiry(browser):
    agent = Client()
    start = post(agent, 'device/start', {'name': 'Agent'}).json()
    assert post(browser, 'device/approve', {'user_code': start['user_code'], 'decision': 'deny'}).status_code == 200
    assert post(agent, 'device/poll', {'device_code': start['device_code']}).status_code == 403
    DeviceGrant.objects.update(expires_at=timezone.now()-timedelta(seconds=1))
    assert browser.get('/api/v2/device/approve', {'user_code': start['user_code']}).status_code == 404

def test_jwt_signature_issuer_party_session_and_expiry():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    now = int(timezone.now().timestamp())
    claims = {'iss': 'https://identity.example', 'sub': 'user_test', 'sid': 'sess_test', 'azp': 'https://kwip.tech', 'iat': now, 'nbf': now, 'exp': now+60}
    with override_settings(MARKET_CLERK_ISSUER=claims['iss'], MARKET_CLERK_PUBLIC_KEY=public):
        assert verify_session(jwt.encode(claims, key, algorithm='RS256'))['sub'] == 'user_test'
        for changes in [{'azp': 'https://evil.example'}, {'iss': 'https://evil.example'}, {'exp': now-10}, {'sts': 'pending'}, {'sid': 'machine_fake'}, {'exp': now+600}]:
            with pytest.raises(Problem):
                verify_session(jwt.encode(claims | changes, key, algorithm='RS256'))
        with pytest.raises(Problem):
            verify_session(jwt.encode(claims, 'wrong-key-that-is-at-least-32-characters', algorithm='HS256'))

@override_settings(MARKET_REQUESTS_PER_MINUTE=2)
def test_workspace_rate_limit(browser):
    assert browser.get('/api/v2/account').status_code == 200
    assert browser.get('/api/v2/account').status_code == 200
    response = browser.get('/api/v2/account')
    assert response.status_code == 429 and int(response['Retry-After']) > 0
