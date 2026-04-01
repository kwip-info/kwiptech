"""Tests for Clerk JWT verification and JWKS caching."""

import json
import time
from unittest.mock import MagicMock, patch

import jwt as pyjwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from django.test import TestCase, override_settings

from plane.auth.jwt import JwtVerificationError, _JwksKeyCache, verify_clerk_token


def _generate_rsa_keypair():
    """Generate an RSA key pair for testing."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    return private_key, public_key


def _public_key_to_jwk(public_key, kid="test-kid"):
    """Convert an RSA public key to JWK dict format."""
    public_numbers = public_key.public_numbers()
    n = public_numbers.n.to_bytes((public_numbers.n.bit_length() + 7) // 8, "big")
    e = public_numbers.e.to_bytes((public_numbers.e.bit_length() + 7) // 8, "big")

    import base64
    return {
        "kty": "RSA",
        "kid": kid,
        "use": "sig",
        "alg": "RS256",
        "n": base64.urlsafe_b64encode(n).rstrip(b"=").decode(),
        "e": base64.urlsafe_b64encode(e).rstrip(b"=").decode(),
    }


def _make_signed_token(private_key, claims, kid="test-kid"):
    """Create a signed JWT with the given claims."""
    return pyjwt.encode(claims, private_key, algorithm="RS256", headers={"kid": kid})


@override_settings(CLERK_JWKS_URL="https://test.clerk.accounts.dev/.well-known/jwks.json")
class TestJwksKeyCache(TestCase):

    def test_refresh_fetches_from_clerk_api(self):
        private_key, public_key = _generate_rsa_keypair()
        jwk = _public_key_to_jwk(public_key)
        jwks_response = json.dumps({"keys": [jwk]}).encode()

        cache = _JwksKeyCache()
        mock_resp = MagicMock()
        mock_resp.read.return_value = jwks_response
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("plane.auth.jwt.urllib.request.urlopen", return_value=mock_resp):
            cache._refresh()

        assert cache._keys is not None
        assert len(cache._keys) == 1

    def test_cache_reuses_keys_within_ttl(self):
        private_key, public_key = _generate_rsa_keypair()
        jwk = _public_key_to_jwk(public_key)
        token = _make_signed_token(private_key, {
            "sub": "user_1", "exp": time.time() + 3600,
            "nbf": time.time() - 10, "iss": "https://test.clerk.accounts.dev",
        })

        cache = _JwksKeyCache()
        cache._keys = [jwk]
        cache._fetched_at = time.time()

        with patch("plane.auth.jwt.urllib.request.urlopen") as mock_fetch:
            cache.get_signing_key(token)
            mock_fetch.assert_not_called()

    @override_settings(CLERK_JWKS_CACHE_TTL=0)
    def test_cache_refreshes_after_ttl(self):
        private_key, public_key = _generate_rsa_keypair()
        jwk = _public_key_to_jwk(public_key)
        jwks_response = json.dumps({"keys": [jwk]}).encode()
        token = _make_signed_token(private_key, {
            "sub": "user_1", "exp": time.time() + 3600,
            "nbf": time.time() - 10, "iss": "https://test.clerk.accounts.dev",
        })

        cache = _JwksKeyCache()
        cache._keys = [jwk]
        cache._fetched_at = time.time() - 10  # Expired with TTL=0

        mock_resp = MagicMock()
        mock_resp.read.return_value = jwks_response
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("plane.auth.jwt.urllib.request.urlopen", return_value=mock_resp) as mock_fetch:
            cache.get_signing_key(token)
            mock_fetch.assert_called_once()


class TestVerifyClerkToken(TestCase):

    def _setup_cache_with_key(self, public_key, kid="test-kid"):
        jwk = _public_key_to_jwk(public_key, kid)
        cache_patch = patch("plane.auth.jwt._cache")
        mock_cache = cache_patch.start()
        self.addCleanup(cache_patch.stop)
        mock_cache.get_signing_key.return_value = (
            pyjwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk))
        )
        return mock_cache

    def test_valid_token_returns_claims(self):
        private_key, public_key = _generate_rsa_keypair()
        self._setup_cache_with_key(public_key)
        claims = {
            "sub": "user_abc123",
            "exp": time.time() + 3600,
            "nbf": time.time() - 10,
            "iss": "https://test.clerk.accounts.dev",
        }
        token = _make_signed_token(private_key, claims)

        result = verify_clerk_token(token)
        assert result["sub"] == "user_abc123"

    def test_expired_token_raises_error(self):
        private_key, public_key = _generate_rsa_keypair()
        self._setup_cache_with_key(public_key)
        claims = {
            "sub": "user_abc123",
            "exp": time.time() - 100,
            "nbf": time.time() - 200,
            "iss": "https://test.clerk.accounts.dev",
        }
        token = _make_signed_token(private_key, claims)

        with self.assertRaises(JwtVerificationError):
            verify_clerk_token(token)

    def test_missing_sub_claim_raises_error(self):
        private_key, public_key = _generate_rsa_keypair()
        self._setup_cache_with_key(public_key)
        claims = {
            "exp": time.time() + 3600,
            "nbf": time.time() - 10,
            "iss": "https://test.clerk.accounts.dev",
        }
        token = _make_signed_token(private_key, claims)

        with self.assertRaises(JwtVerificationError):
            verify_clerk_token(token)
