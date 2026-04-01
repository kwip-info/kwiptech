"""Clerk JWT verification with JWKS key caching."""

import json
import logging
import time
import urllib.request

import jwt
from django.conf import settings

logger = logging.getLogger(__name__)


class JwtVerificationError(Exception):
    """Raised when a Clerk JWT cannot be verified."""


class _JwksKeyCache:
    """Fetches and caches JWKS signing keys from Clerk."""

    def __init__(self):
        self._keys = None
        self._fetched_at = 0.0

    def get_signing_key(self, token):
        """Return the RSA public key matching the token's kid header."""
        unverified = jwt.get_unverified_header(token)
        kid = unverified.get("kid")
        if not kid:
            raise JwtVerificationError("Token header missing kid")

        key = self._find_key(kid)
        if key is not None:
            return key

        # Key not found — maybe Clerk rotated keys. Force refresh once.
        if self._is_stale():
            self._refresh()
            key = self._find_key(kid)

        if key is None:
            raise JwtVerificationError(f"No matching key for kid={kid}")
        return key

    def _find_key(self, kid):
        """Look up a key by kid, refreshing if cache is expired."""
        if self._keys is None or self._is_expired():
            self._refresh()

        for jwk in self._keys or []:
            if jwk.get("kid") == kid:
                return jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk))
        return None

    def _is_expired(self):
        return (time.time() - self._fetched_at) > settings.CLERK_JWKS_CACHE_TTL

    def _is_stale(self):
        return (time.time() - self._fetched_at) > 60

    def _refresh(self):
        """Fetch JWKS from Clerk's public endpoint."""
        try:
            if not settings.CLERK_JWKS_URL:
                raise JwtVerificationError("CLERK_JWKS_URL not configured")
            req = urllib.request.Request(settings.CLERK_JWKS_URL)
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                self._keys = data.get("keys", [])
                self._fetched_at = time.time()
        except Exception:
            logger.exception("Failed to fetch JWKS from Clerk")
            if self._keys is None:
                raise JwtVerificationError("Cannot fetch JWKS and no cached keys")


_cache = _JwksKeyCache()


def verify_clerk_token(token):
    """Verify a Clerk session JWT. Returns the decoded claims dict."""
    try:
        key = _cache.get_signing_key(token)
        return jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            leeway=10,
            options={
                "require": ["exp", "nbf", "sub"],
                "verify_aud": False,
            },
        )
    except JwtVerificationError:
        raise
    except jwt.ExpiredSignatureError as exc:
        raise JwtVerificationError("Token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise JwtVerificationError(f"Invalid token: {exc}") from exc
