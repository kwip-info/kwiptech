"""API key authentication for the management plane.

Authenticates requests using the ``Authorization: Bearer psc_...`` header.
Looks up the key by hash — the raw key is never stored.
"""

from __future__ import annotations

from django.utils import timezone
from rest_framework import authentication, exceptions

from plane.core.models import Account, ApiKey


class ApiKeyAuthentication(authentication.BaseAuthentication):
    """Authenticate requests via pyscoped API key in Bearer header."""

    def authenticate(self, request):
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith("Bearer "):
            return None

        raw_key = auth_header[7:].strip()
        if not raw_key.startswith("psc_"):
            return None

        key_hash = ApiKey.hash_key(raw_key)

        try:
            api_key = ApiKey.objects.select_related("account").get(
                key_hash=key_hash, is_active=True
            )
        except ApiKey.DoesNotExist:
            raise exceptions.AuthenticationFailed("Invalid or revoked API key.")

        # Update last_used_at
        ApiKey.objects.filter(id=api_key.id).update(last_used_at=timezone.now())

        # Return (user_proxy, auth_info)
        # DRF expects (user, auth) — we use the account as the "user"
        return (api_key.account, api_key)
