"""Map authenticated requests to pyscoped principals.

The pyscoped Django middleware calls this function on every request
to determine who is acting. We map the API-key-authenticated account
to a pyscoped principal, creating one lazily if it doesn't exist.

This is the dogfooding bridge: every management plane operation
(key creation, batch ingest, usage query) is attributed to a pyscoped
principal and appears in the pyscoped audit trail.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def resolve_principal(request):
    """Resolve the acting pyscoped principal from the request.

    Called by ``ScopedContextMiddleware`` via the
    ``SCOPED_PRINCIPAL_RESOLVER`` setting.

    Returns:
        A pyscoped ``Principal`` object, or ``None`` if the request
        is unauthenticated.
    """
    # Dashboard auth (Clerk JWT) sets clerk_user; API auth sets user
    account = getattr(request, "clerk_user", None)
    if account is None:
        account = getattr(request, "user", None)
    if account is None or not hasattr(account, "id"):
        return None

    # Lazy-import to avoid circular imports at settings load time
    from scoped.contrib.django import get_client

    client = get_client()

    # Try to find an existing principal for this account
    principal = client.principals.find(account.id)
    if principal is not None:
        return principal

    # First time this account hits the platform — create a principal
    try:
        return client.principals.create(
            str(account),
            kind="account",
            principal_id=account.id,
        )
    except Exception:
        # Principal may already exist (race condition or registry conflict)
        logger.debug("Principal create failed for %s, retrying find", account.id)
        return client.principals.find(account.id)
