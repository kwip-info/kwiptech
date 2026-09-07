"""Clerk identity revocation. Verification follows Svix's documented HMAC format.

https://www.svix.com/guides/receiving/receive-webhooks-with-python/
Only signed deletion/termination events alter state; creation never restores users.
"""
import base64
import binascii
import hashlib
import hmac
import json
from django.conf import settings
from django.core.exceptions import RequestDataTooBig
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from .errors import Problem
from .models import Identity, IdentityEvent, Workspace, ServiceKey, RevokedSession


def verify(body, headers):
    secret = getattr(settings, 'MARKET_CLERK_WEBHOOK_SECRET', '')
    if not secret:
        raise Problem('identity_webhook_unavailable', 'Identity webhook is not configured.', 503)
    message_id = headers.get('svix-id') or headers.get('webhook-id', '')
    timestamp = headers.get('svix-timestamp') or headers.get('webhook-timestamp', '')
    signatures = headers.get('svix-signature') or headers.get('webhook-signature', '')
    try:
        if not isinstance(message_id, str) or not 1 <= len(message_id) <= 255 or len(timestamp) > 20 or len(signatures) > 4096:
            raise ValueError
        if abs(timezone.now().timestamp() - int(timestamp)) > 300:
            raise ValueError
        if not secret.startswith('whsec_'):
            raise ValueError
        key = base64.b64decode(secret[6:], validate=True)
        if len(key) < 16:
            raise ValueError
        content = message_id.encode() + b'.' + timestamp.encode() + b'.' + body
        expected = base64.b64encode(hmac.new(key, content, hashlib.sha256).digest()).decode()
        matches = [hmac.compare_digest(sig[3:], expected) for sig in signatures.split() if sig.startswith('v1,')]
        if not any(matches):
            raise ValueError
        payload = json.loads(body)
        if not isinstance(payload, dict) or not isinstance(payload.get('type'), str) or len(payload['type']) > 100 or not isinstance(payload.get('data'), dict):
            raise ValueError
        return message_id, payload
    except (ValueError, TypeError, UnicodeDecodeError, binascii.Error, RecursionError) as exc:
        raise Problem('invalid_signature', 'Invalid identity webhook.', 400) from exc


def apply_event(message_id, payload):
    event_type, data = payload['type'], payload['data']
    subject = data.get('id') if event_type == 'user.deleted' else data.get('user_id', '')
    session_id = data.get('id') if event_type in ('session.ended', 'session.revoked', 'session.removed') else None
    if event_type == 'user.deleted' and (not isinstance(subject, str) or not subject.startswith('user_') or len(subject) > 255):
        raise Problem('invalid_event', 'Invalid user deletion event.')
    if session_id is not None and (not isinstance(session_id, str) or not session_id.startswith('sess_') or len(session_id) > 255):
        raise Problem('invalid_event', 'Invalid session event.')
    subject = subject if isinstance(subject, str) and len(subject) <= 255 else ''
    with transaction.atomic():
        event, created = IdentityEvent.objects.get_or_create(message_id=message_id, defaults={'event_type': event_type, 'subject': subject})
        if not created:
            if event.event_type != event_type or event.subject != subject:
                raise Problem('event_conflict', 'This event identifier has different content.', 409)
            return
        if event_type == 'user.deleted':
            identity, _ = Identity.objects.get_or_create(subject=subject, defaults={'active': False, 'deleted_at': timezone.now()})
            # Match key issuance lock order. No pending-device lock is needed: an
            # inactive owner invalidates all approved grants and service credentials.
            workspace = Workspace.objects.select_for_update().filter(owner=identity).first()
            identity = Identity.objects.select_for_update().get(pk=identity.pk)
            identity.active = False
            identity.deleted_at = identity.deleted_at or timezone.now()
            identity.save(update_fields=['active', 'deleted_at'])
            if workspace:
                ServiceKey.objects.filter(workspace=workspace, revoked_at__isnull=True).update(revoked_at=timezone.now())
                from django.apps import apps
                if apps.is_installed('plane.commerce'):
                    from plane.commerce.models import BillingAccount
                    BillingAccount.objects.filter(workspace=workspace).update(
                        overage_enabled=False, cancellation_requested_at=timezone.now(), cancellation_completed_at=None)
        elif session_id:
            RevokedSession.objects.get_or_create(session_id=session_id, defaults={'subject': subject})


@csrf_exempt
def clerk_webhook(request):
    if request.method != 'POST':
        return JsonResponse({'error': {'code': 'method_not_allowed'}}, status=405, headers={'Allow': 'POST', 'Cache-Control': 'no-store'})
    try:
        if int(request.META.get('CONTENT_LENGTH') or 0) > 1048576:
            raise Problem('body_too_large', 'Webhook exceeds allowed size.', 413)
        body = request.body
        if len(body) > 1048576:
            raise Problem('body_too_large', 'Webhook exceeds allowed size.', 413)
        message_id, payload = verify(body, request.headers)
        apply_event(message_id, payload)
        response = JsonResponse({'received': True})
    except (ValueError, RequestDataTooBig):
        response = JsonResponse({'error': {'code': 'invalid_body'}}, status=400)
    except Problem as exc:
        response = JsonResponse({'error': {'code': exc.code, 'message': exc.message}}, status=exc.status)
    response['Cache-Control'] = 'no-store'
    return response
