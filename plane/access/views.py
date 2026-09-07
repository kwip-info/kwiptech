import secrets
from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from django.conf import settings
from .auth import READ_SCOPES, digest, issue_key, rate_limit, client_peer
from .errors import Problem
from .http import endpoint, body_json
from .models import DeviceGrant, ServiceKey


def key_json(key):
    return {'id': str(key.pk), 'name': key.name, 'prefix': key.prefix, 'scopes': key.scopes,
            'dataset_slugs': key.dataset_slugs, 'source_slugs': key.source_slugs,
            'expires_at': key.expires_at.isoformat(), 'revoked': key.revoked_at is not None}

@endpoint()
def account(request, principal):
    return {'id': str(principal.workspace.pk), 'name': principal.workspace.name,
            'operator': principal.workspace.owner.is_operator, 'authentication': principal.kind}

@endpoint(('GET', 'POST'))
def keys(request, principal):
    principal.require_browser()
    if request.method == 'GET':
        return {'keys': [key_json(k) for k in principal.workspace.keys.order_by('-created_at')[:100]]}
    data = body_json(request)
    # Keep management responses bounded and make accidental key proliferation visible.
    with transaction.atomic():
        from .models import Workspace
        Workspace.objects.select_for_update().get(pk=principal.workspace.pk)
        if principal.workspace.keys.filter(revoked_at__isnull=True, expires_at__gt=timezone.now()).count() >= 50:
            raise Problem('key_limit', 'Revoke an existing key before creating another.', 409)
        key, token = issue_key(principal.workspace, data.get('name'), data.get('scopes'), data.get('days', 90),
                               data.get('dataset_slugs'), data.get('source_slugs'))
    return {'key': key_json(key), 'token': token, 'notice': 'Copy this key now. It will not be shown again.'}

@endpoint(('DELETE',))
def revoke_key(request, principal, key_id):
    principal.require_browser()
    with transaction.atomic():
        from .models import Workspace
        Workspace.objects.select_for_update().get(pk=principal.workspace.pk)
        key = ServiceKey.objects.select_for_update().filter(workspace=principal.workspace, pk=key_id).first()
        if not key:
            raise Problem('not_found', 'Key not found.', 404)
        if not key.revoked_at:
            key.revoked_at = timezone.now()
            key.save(update_fields=['revoked_at'])
    return {'revoked': True}

@endpoint(('POST',), authenticated=False)
def device_start(request, principal):
    rate_limit('device-start:' + client_peer(request), 10)
    data = body_json(request, 4096)
    name, scopes = data.get('name'), data.get('scopes', ['datasets:read'])
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise Problem('invalid_name', 'Provide the name of the agent connecting to your account.')
    if not isinstance(scopes, list) or not scopes or any(not isinstance(s, str) or s not in READ_SCOPES for s in scopes):
        raise Problem('invalid_scopes', 'Agent linking supports datasets:read and exports:read only.')
    device = secrets.token_urlsafe(32)
    code = ''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(8))
    grant = DeviceGrant.objects.create(device_hash=digest(device), user_code=code, name=name.strip(),
                                      scopes=sorted(set(scopes)), expires_at=timezone.now() + timedelta(minutes=10))
    return {'device_code': device, 'user_code': grant.user_code, 'verification_uri': settings.MARKET_ORIGIN + '/account/connect',
            'expires_in': 600, 'interval': 5, 'notice': 'KWIP device linking; this is not an OAuth token endpoint.'}

@endpoint(('GET', 'POST'))
def device_approval(request, principal):
    principal.require_browser()
    data = body_json(request, 4096) if request.method == 'POST' else request.GET
    code = data.get('user_code', '')
    if not isinstance(code, str) or len(code) > 12:
        raise Problem('invalid_code', 'Enter the code displayed by your agent.')
    with transaction.atomic():
        grant = DeviceGrant.objects.select_for_update().filter(user_code=code.upper().replace('-', '').strip()).first()
        if not grant or grant.expires_at <= timezone.now() or grant.status != 'pending':
            raise Problem('invalid_code', 'This code is invalid, expired, or already used.', 404)
        result = {'name': grant.name, 'scopes': grant.scopes, 'expires_at': grant.expires_at.isoformat(),
                  'notice': 'Approve only if you initiated this connection. It grants access to your account allowance.'}
        if request.method == 'POST':
            decision = data.get('decision')
            if decision not in ('approve', 'deny'):
                raise Problem('invalid_decision', 'Choose approve or deny explicitly.')
            grant.workspace = principal.workspace
            grant.status = 'approved' if decision == 'approve' else 'denied'
            grant.save(update_fields=['workspace', 'status'])
            result['status'] = grant.status
    return result

@endpoint(('POST',), authenticated=False)
def device_poll(request, principal):
    data = body_json(request, 4096)
    code = data.get('device_code', '')
    if not isinstance(code, str) or not 20 <= len(code) <= 100:
        raise Problem('invalid_grant', 'Invalid device code.', 400)
    rate_limit('device-poll-ip:' + client_peer(request), 60)
    problem = None
    result = None
    with transaction.atomic():
        grant = DeviceGrant.objects.select_for_update(of=('self',)).select_related('workspace__owner').filter(device_hash=digest(code)).first()
        if not grant or grant.expires_at <= timezone.now() or grant.status == 'consumed':
            raise Problem('expired_grant', 'Start a new connection request.', 400)
        if grant.last_poll_at and (timezone.now() - grant.last_poll_at).total_seconds() < 5:
            raise Problem('slow_down', 'Wait at least five seconds between polls.', 429, retry_after=5)
        grant.last_poll_at = timezone.now()
        if grant.status == 'pending':
            problem = Problem('authorization_pending', 'Waiting for your approval.', 400)
        elif grant.status == 'denied' or not grant.workspace.owner.active:
            problem = Problem('access_denied', 'This connection was denied.', 403)
        else:
            from .models import Workspace
            Workspace.objects.select_for_update().get(pk=grant.workspace_id)
            if grant.workspace.keys.filter(revoked_at__isnull=True, expires_at__gt=timezone.now()).count() >= 50:
                problem = Problem('key_limit', 'Revoke an existing key and start again.', 409)
            else:
                key, token = issue_key(grant.workspace, grant.name, grant.scopes)
                grant.status = 'consumed'
                result = {'access_token': token, 'token_type': 'Bearer', 'key_id': str(key.pk),
                          'expires_at': key.expires_at.isoformat(), 'scopes': key.scopes}
        grant.save(update_fields=['last_poll_at', 'status'])
    # Pending polls must commit their timestamps even though the response is an error.
    if problem:
        raise problem
    return result
