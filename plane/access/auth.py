import hashlib
import ipaddress
import re
import secrets
from dataclasses import dataclass
from datetime import timedelta
import jwt
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from .errors import Problem
from .models import Identity, Workspace, ServiceKey, RateBucket, RevokedSession

READ_SCOPES = {'datasets:read', 'exports:read'}
ALL_SCOPES = READ_SCOPES | {'ingest:write'}

def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

@dataclass
class Principal:
    workspace: Workspace
    kind: str
    key: ServiceKey | None = None

    def require(self, scope, dataset=None, source=None):
        if scope == 'ingest:write' and not self.workspace.owner.is_operator:
            raise Problem('forbidden', 'Publisher access is restricted to KWIP operators.', 403)
        if self.key:
            if scope not in self.key.scopes:
                raise Problem('insufficient_scope', f'This key requires {scope}.', 403)
            if dataset and self.key.dataset_slugs and dataset not in self.key.dataset_slugs:
                raise Problem('dataset_forbidden', 'This key cannot access that dataset.', 403)
            if source and self.key.source_slugs and source not in self.key.source_slugs:
                raise Problem('source_forbidden', 'This key cannot publish that source.', 403)

    def require_browser(self):
        if self.kind != 'session':
            raise Problem('browser_required', 'Use your signed-in account to manage access and billing.', 403)

def verify_session(token):
    issuer = settings.MARKET_CLERK_ISSUER
    if not issuer:
        raise Problem('identity_unavailable', 'Account sign-in is not configured.', 503)
    try:
        from .jwks import signing_key
        key = settings.MARKET_CLERK_PUBLIC_KEY or signing_key(issuer, token)
        claims = jwt.decode(token, key, algorithms=['RS256'], issuer=issuer,
                            options={'verify_aud': False, 'require': ['exp', 'iat', 'nbf', 'iss', 'sub', 'sid']}, leeway=5)
        if claims.get('azp') not in settings.MARKET_AUTHORIZED_PARTIES:
            raise ValueError('unauthorized party')
        if claims.get('sts', 'active') != 'active' or not isinstance(claims['sub'], str) or not claims['sub'].startswith('user_'):
            raise ValueError('not an active user session')
        if not isinstance(claims['sid'], str) or not claims['sid'].startswith('sess_'):
            raise ValueError('not a session token')
        if claims['exp'] - claims['iat'] > 120:
            raise ValueError('session token lifetime exceeds allowed bound')
        if RevokedSession.objects.filter(session_id=claims['sid']).exists():
            raise ValueError('revoked session')
        return claims
    except (jwt.PyJWTError, ValueError, TypeError, KeyError) as exc:
        raise Problem('invalid_token', 'The session is invalid or expired. Sign in again.', 401) from exc

def client_peer(request):
    peer = request.META.get('REMOTE_ADDR', '')
    if settings.MARKET_TRUST_HEROKU_PROXY:
        # Heroku appends its observed peer on the right. Never trust leftmost XFF
        # or CF-Connecting-IP without separately verifying proxy CIDR ownership.
        peer = request.headers.get('X-Forwarded-For', peer).split(',')[-1].strip()
    try:
        return str(ipaddress.ip_address(peer))
    except ValueError:
        return 'unknown'

def authenticate(request):
    rate_limit('auth-peer:' + client_peer(request), getattr(settings, 'MARKET_AUTH_ATTEMPTS_PER_MINUTE', 600))
    header = request.headers.get('Authorization', '')
    if not header.startswith('Bearer ') or len(header) > 16384:
        raise Problem('authentication_required', 'Send an Authorization: Bearer token.', 401)
    token = header[7:]
    if token.startswith('kwip_'):
        key = ServiceKey.objects.select_related('workspace__owner').filter(token_hash=digest(token)).first()
        if not key or key.revoked_at or key.expires_at <= timezone.now() or not key.workspace.owner.active or key.workspace.owner.deleted_at:
            raise Problem('invalid_token', 'This key is invalid, expired, or revoked.', 401)
        principal = Principal(key.workspace, 'service', key)
    else:
        rate_limit('jwt-peer:' + client_peer(request), 120)
        claims = verify_session(token)
        with transaction.atomic():
            identity, _ = Identity.objects.get_or_create(subject=claims['sub'])
            if not identity.active or identity.deleted_at:
                raise Problem('account_disabled', 'This account is disabled.', 403)
            workspace, _ = Workspace.objects.get_or_create(owner=identity)
        principal = Principal(workspace, 'session')
    rate_limit('workspace:' + str(principal.workspace.pk), settings.MARKET_REQUESTS_PER_MINUTE)
    return principal

def rate_limit(key, limit, seconds=60):
    now = timezone.now()
    # get_or_create's unique constraint resolves concurrent first-use insertion.
    with transaction.atomic():
        RateBucket.objects.get_or_create(key=digest(key))
        row = RateBucket.objects.select_for_update().get(pk=digest(key))
        if (now - row.starts_at).total_seconds() >= seconds:
            row.starts_at, row.count = now, 0
        if row.count >= limit:
            raise Problem('rate_limited', 'Too many requests. Retry after the current window.', 429,
                          retry_after=max(1, seconds - int((now - row.starts_at).total_seconds())))
        row.count += 1
        row.save(update_fields=['starts_at', 'count'])

@transaction.atomic
def issue_key(workspace, name, scopes, days=90, dataset_slugs=None, source_slugs=None):
    workspace = Workspace.objects.select_for_update().select_related('owner').get(pk=workspace.pk)
    if not workspace.owner.active or workspace.owner.deleted_at:
        raise Problem('account_disabled', 'This account is disabled.', 403)
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise Problem('invalid_name', 'Provide a key name of 1–80 characters.')
    if not isinstance(scopes, list) or not scopes or any(not isinstance(s, str) or s not in ALL_SCOPES for s in scopes):
        raise Problem('invalid_scopes', 'Choose explicit supported scopes.')
    if 'ingest:write' in scopes and not workspace.owner.is_operator:
        raise Problem('forbidden', 'Only operators can create publishing keys.', 403)
    if type(days) is not int or not 1 <= days <= 365:
        raise Problem('invalid_expiry', 'Key lifetime must be 1–365 days.')
    for values in (dataset_slugs, source_slugs):
        if values is not None and (not isinstance(values, list) or len(values) > 100 or any(not isinstance(v, str) or not 1 <= len(v) <= 100 for v in values)):
            raise Problem('invalid_restrictions', 'Restrictions must be a list of dataset/source slugs.')
    if 'ingest:write' in scopes and (not dataset_slugs or not source_slugs):
        raise Problem('publisher_restrictions_required', 'Publishing keys require explicit dataset and source restrictions.')
    for values in (dataset_slugs or [], source_slugs or []):
        if any(not re.fullmatch(r'[a-zA-Z0-9_-]+', value) for value in values):
            raise Problem('invalid_restrictions', 'Use exact dataset and source slugs.')
    token = 'kwip_' + secrets.token_urlsafe(32)
    key = ServiceKey.objects.create(workspace=workspace, name=name.strip(), scopes=sorted(set(scopes)),
                                   token_hash=digest(token), prefix=token[:14], expires_at=timezone.now() + timedelta(days=days),
                                   dataset_slugs=dataset_slugs or [], source_slugs=source_slugs or [])
    return key, token


def refresh_principal(principal, *, lock=False):
    """Recheck authority at the delivery boundary, after any workspace-lock wait.

    Mutations/revocation and delivery share workspace -> key lock order. The caller
    must hold an atomic transaction when lock=True.
    """
    workspaces = Workspace.objects.select_for_update() if lock else Workspace.objects
    workspace = workspaces.get(pk=principal.workspace.pk)
    if not workspace.owner.active or workspace.owner.deleted_at:
        raise Problem('account_disabled', 'This account is disabled.', 403)
    if principal.kind == 'service':
        keys = ServiceKey.objects.select_for_update() if lock else ServiceKey.objects
        key = keys.filter(pk=getattr(principal.key, 'pk', None), workspace=workspace).first()
        if key is None or key.revoked_at or key.expires_at <= timezone.now():
            raise Problem('invalid_token', 'This key is invalid, expired, or revoked.', 401)
        return Principal(workspace, 'service', key)
    if principal.kind != 'session':
        raise Problem('invalid_token', 'Unknown authentication context.', 401)
    return Principal(workspace, 'session')
