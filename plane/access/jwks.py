"""Database-shared JWKS cache with a global per-issuer refresh cooldown."""
import json
import urllib.request
import urllib.error
import jwt
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from .errors import Problem
from .models import JWKSnapshot


def signing_key(issuer, token):
    header = jwt.get_unverified_header(token)
    kid = header.get('kid')
    if header.get('alg') != 'RS256' or not isinstance(kid, str) or not 1 <= len(kid) <= 200:
        raise jwt.InvalidTokenError('Invalid signing key header')
    # Unverified claims only reject obvious foreign tokens early; verified decode
    # still checks issuer/signature/expiry after obtaining our own trusted key.
    claims = jwt.decode(token, options={'verify_signature': False})
    if claims.get('iss') != issuer:
        raise jwt.InvalidTokenError('Wrong issuer')
    key_data = None
    failure = None
    with transaction.atomic():
        JWKSnapshot.objects.get_or_create(issuer=issuer)
        cache = JWKSnapshot.objects.select_for_update().get(pk=issuer)
        now = timezone.now()
        ttl = getattr(settings, 'MARKET_JWKS_CACHE_SECONDS', 300)
        cooldown = getattr(settings, 'MARKET_JWKS_REFRESH_SECONDS', 60)
        fresh = cache.fetched_at and (now - cache.fetched_at).total_seconds() < ttl
        known = next((key for key in cache.document.get('keys', []) if key.get('kid') == kid), None)
        if not fresh or known is None:
            can_refresh = not cache.last_attempt_at or (now - cache.last_attempt_at).total_seconds() >= cooldown
            if can_refresh:
                cache.last_attempt_at = now
                try:
                    request = urllib.request.Request(issuer.rstrip('/') + '/.well-known/jwks.json', headers={'Accept': 'application/json'})
                    with urllib.request.urlopen(request, timeout=getattr(settings, 'MARKET_JWKS_TIMEOUT_SECONDS', 5)) as response:
                        raw = response.read(262145)
                    if len(raw) > 262144:
                        raise ValueError('Oversized key set')
                    document = json.loads(raw)
                    if not isinstance(document, dict) or not isinstance(document.get('keys'), list) or not 1 <= len(document['keys']) <= 64 or any(not isinstance(key, dict) for key in document['keys']):
                        raise ValueError('Invalid key set')
                    cache.document, cache.fetched_at = document, now
                    fresh = True
                    known = next((key for key in document['keys'] if key.get('kid') == kid), None)
                except (urllib.error.URLError, TimeoutError, OSError, ValueError, RecursionError):
                    failure = Problem('identity_unavailable', 'Identity verification is temporarily unavailable.', 503)
                cache.save(update_fields=['document', 'fetched_at', 'last_attempt_at'])
            elif not fresh:
                failure = Problem('identity_unavailable', 'Identity verification is temporarily unavailable.', 503)
        if fresh and known:
            key_data = known
    # Raise after commit so failed fetches retain their retry cooldown.
    if key_data:
        if key_data.get('kty') != 'RSA' or key_data.get('use', 'sig') != 'sig' or key_data.get('alg', 'RS256') != 'RS256':
            raise jwt.InvalidTokenError('Invalid RSA signing key')
        return jwt.PyJWK.from_dict(key_data, algorithm='RS256').key
    if failure:
        raise failure
    raise jwt.InvalidTokenError('Unknown signing key')
