import base64
import hashlib
import hmac
import json
import ssl
from datetime import timedelta
from unittest.mock import Mock, patch
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from django.test import RequestFactory, override_settings
from django.utils import timezone
from plane.access.auth import authenticate, issue_key, verify_session
from plane.access.errors import Problem
from plane.access.models import Identity, IdentityEvent, Workspace, ServiceKey, RevokedSession, JWKSnapshot
from plane.access.webhooks import apply_event, verify, clerk_webhook

pytestmark = pytest.mark.django_db
SECRET = 'whsec_' + base64.b64encode(b'synthetic-test-secret-32-bytes!!!').decode()


def signed(event, message='msg_test', timestamp=None):
    body = json.dumps(event).encode()
    timestamp = str(timestamp if timestamp is not None else int(timezone.now().timestamp()))
    key = base64.b64decode(SECRET[6:])
    sig = base64.b64encode(hmac.new(key, message.encode()+b'.'+timestamp.encode()+b'.'+body, hashlib.sha256).digest()).decode()
    return body, {'svix-id': message, 'svix-timestamp': timestamp, 'svix-signature': 'v1,'+sig}


@override_settings(MARKET_CLERK_WEBHOOK_SECRET=SECRET)
def test_signature_replay_and_mutation():
    event = {'type': 'user.deleted', 'data': {'id': 'user_deleted'}}
    body, headers = signed(event)
    message_id, verified = verify(body, headers)
    apply_event(message_id, verified)
    apply_event(message_id, verified)
    assert IdentityEvent.objects.count() == 1
    identity = Identity.objects.get(subject='user_deleted')
    assert not identity.active and identity.deleted_at
    with pytest.raises(Problem):
        verify(body+b' ', headers)
    for delta in [-301, 301]:
        body, headers = signed(event, timestamp=int(timezone.now().timestamp())+delta)
        with pytest.raises(Problem):
            verify(body, headers)
    body, headers = signed(event)
    headers['svix-signature'] = 'v2,ignored v1,incorrect ' + headers['svix-signature']
    assert verify(body, headers)[0] == 'msg_test'


def test_user_deletion_revokes_keys_and_cannot_restore():
    identity = Identity.objects.create(subject='user_deleted')
    workspace = Workspace.objects.create(owner=identity)
    key, token = issue_key(workspace, 'Agent', ['datasets:read'])
    apply_event('msg_delete', {'type': 'user.deleted', 'data': {'id': identity.subject}})
    key.refresh_from_db()
    assert key.revoked_at
    apply_event('msg_create_old', {'type': 'user.created', 'data': {'id': identity.subject}})
    apply_event('msg_update_old', {'type': 'user.updated', 'data': {'id': identity.subject}})
    identity.refresh_from_db()
    assert not identity.active and identity.deleted_at
    with pytest.raises(Problem):
        issue_key(workspace, 'Stale workspace object', ['datasets:read'])
    request = RequestFactory().get('/account', HTTP_AUTHORIZATION='Bearer '+token)
    with pytest.raises(Problem):
        authenticate(request)
    # Even an accidental active flag change does not erase the permanent tombstone.
    Identity.objects.filter(pk=identity.pk).update(active=True)
    with patch('plane.access.auth.verify_session', return_value={'sub': identity.subject}), pytest.raises(Problem):
        authenticate(RequestFactory().get('/account', HTTP_AUTHORIZATION='Bearer fake-session'))


def signed_session():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    now = int(timezone.now().timestamp())
    claims = {'iss': 'https://identity.example', 'sub': 'user_test', 'sid': 'sess_test', 'azp': 'https://kwip.tech', 'iat': now, 'nbf': now, 'exp': now+60}
    return key, public, claims


@pytest.mark.parametrize('event_type', ['session.ended', 'session.revoked', 'session.removed'])
def test_session_termination_rejects_unexpired_jwt(event_type):
    key, public, claims = signed_session()
    token = jwt.encode(claims, key, algorithm='RS256')
    with override_settings(MARKET_CLERK_ISSUER=claims['iss'], MARKET_CLERK_PUBLIC_KEY=public):
        assert verify_session(token)['sid'] == 'sess_test'
        apply_event('msg_session', {'type': event_type, 'data': {'id': 'sess_test', 'user_id': 'user_test'}})
        with pytest.raises(Problem):
            verify_session(token)
    assert RevokedSession.objects.count() == 1


@override_settings(MARKET_CLERK_ISSUER='https://identity.example', MARKET_CLERK_PUBLIC_KEY='')
def test_unknown_kid_refresh_is_bounded_and_shared():
    key, public, claims = signed_session()
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True) | {'kid': 'known', 'use': 'sig', 'alg': 'RS256'}
    response = Mock()
    response.read.return_value = json.dumps({'keys': [jwk]}).encode()
    context = Mock()
    context.__enter__ = Mock(return_value=response)
    context.__exit__ = Mock(return_value=False)
    with patch('urllib.request.urlopen', return_value=context) as fetch:
        good = jwt.encode(claims, key, algorithm='RS256', headers={'kid': 'known'})
        assert verify_session(good)['sub'] == 'user_test'
        tls_context = fetch.call_args.kwargs['context']
        assert tls_context.verify_mode == ssl.CERT_REQUIRED
        assert tls_context.check_hostname is True
        assert tls_context.cert_store_stats()['x509_ca'] > 0
        for n in range(10):
            token = jwt.encode(claims, key, algorithm='RS256', headers={'kid': 'unknown-'+str(n)})
            with pytest.raises(Problem):
                verify_session(token)
        assert verify_session(good)['sub'] == 'user_test'
        assert fetch.call_count == 1
        JWKSnapshot.objects.update(last_attempt_at=timezone.now()-timedelta(seconds=61))
        with pytest.raises(Problem):
            verify_session(token)
        assert fetch.call_count == 2


@override_settings(MARKET_CLERK_ISSUER='https://identity.example', MARKET_CLERK_PUBLIC_KEY='')
def test_failed_key_fetch_cooldown_survives_error():
    key, public, claims = signed_session()
    token = jwt.encode(claims, key, algorithm='RS256', headers={'kid': 'unknown'})
    with patch('urllib.request.urlopen', side_effect=OSError('temporary failure')) as fetch:
        for _ in range(2):
            with pytest.raises(Problem) as exc:
                verify_session(token)
            assert exc.value.status == 503
        assert fetch.call_count == 1
    assert JWKSnapshot.objects.get().last_attempt_at


@override_settings(MARKET_CLERK_WEBHOOK_SECRET=SECRET)
def test_clerk_webhook_exact_raw_request_and_status():
    body, headers = signed({'type': 'user.deleted', 'data': {'id': 'user_endpoint'}})
    request = RequestFactory().post('/integrations/clerk', data=body, content_type='application/json',
        HTTP_SVIX_ID=headers['svix-id'], HTTP_SVIX_TIMESTAMP=headers['svix-timestamp'], HTTP_SVIX_SIGNATURE=headers['svix-signature'])
    assert clerk_webhook(request).status_code == 200
    assert clerk_webhook(RequestFactory().get('/integrations/clerk')).status_code == 405


@pytest.mark.django_db(transaction=True)
def test_postgres_delete_and_key_issuance_race():
    from concurrent.futures import ThreadPoolExecutor
    from django.db import connection, connections
    if connection.vendor != 'postgresql':
        pytest.skip('Row-lock concurrency requires PostgreSQL.')
    identity = Identity.objects.create(subject='user_race')
    workspace = Workspace.objects.create(owner=identity)
    def issue():
        try:
            try:
                issue_key(workspace, 'Concurrent key', ['datasets:read'])
            except Problem as exc:
                assert exc.code == 'account_disabled'
        finally:
            connections.close_all()
    def delete():
        try:
            apply_event('msg_race', {'type': 'user.deleted', 'data': {'id': identity.subject}})
        finally:
            connections.close_all()
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(issue), executor.submit(delete)]
        for future in futures:
            future.result(timeout=5)
    assert not ServiceKey.objects.filter(workspace=workspace, revoked_at__isnull=True).exists()
    assert not Identity.objects.get(pk=identity.pk).active
