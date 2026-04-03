"""Template context processors for the dashboard."""

from django.conf import settings


def clerk_settings(request):
    """Inject Clerk and org configuration into template context."""
    return {
        "CLERK_PUBLISHABLE_KEY": settings.CLERK_PUBLISHABLE_KEY,
        "clerk_user": getattr(request, "clerk_user", None),
        "organization": getattr(request, "organization", None),
        "membership": getattr(request, "membership", None),
        "effective_role": getattr(request, "effective_role", None),
        "permissions": getattr(request, "permissions", set()),
    }
