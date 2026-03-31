"""Map authenticated requests to pyscoped principals.

The pyscoped Django middleware calls this function on every request
to determine who is acting. We map the API-key-authenticated account
to a pyscoped principal, creating one lazily if it doesn't exist.

This is the dogfooding bridge: every management plane operation
(key creation, batch ingest, usage query) is attributed to a pyscoped
principal and appears in the pyscoped audit trail.
"""

from __future__ import annotations


def resolve_principal(request):
    """Resolve the acting pyscoped principal from the request.

    Called by ``ScopedContextMiddleware`` via the
    ``SCOPED_PRINCIPAL_RESOLVER`` setting.

    Returns:
        A pyscoped ``Principal`` object, or ``None`` if the request
        is unauthenticated.
    """
    # request.user is set by DRF's ApiKeyAuthentication to the Account
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
    return client.principals.create(
        str(account),
        kind="account",
        principal_id=account.id,
    )
