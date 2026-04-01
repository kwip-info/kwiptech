"""Helpers for using the scoped client in dashboard views.

The ScopedContextMiddleware (from the SDK) wraps non-exempt requests
in transaction.atomic() and sets the principal context. This module
provides a convenience accessor for the scoped client.

For write operations in services, use scoped_operation() which adds
an additional nested atomic() for safety.
"""

from contextlib import contextmanager

from django.db import transaction


def get_client():
    """Return the scoped client singleton."""
    from scoped.contrib.django import get_client as _get_client

    return _get_client()


@contextmanager
def scoped_operation():
    """Context manager for scoped write operations.

    Wraps in transaction.atomic() for SAVEPOINT support.
    The middleware already provides an outer transaction, so this
    creates a nested savepoint for the specific operation.

    Usage:
        with scoped_operation() as client:
            obj, v = client.objects.create("api_key", data={...})
    """
    client = get_client()
    with transaction.atomic():
        yield client
