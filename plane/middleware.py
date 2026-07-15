"""Platform-specific middleware customizations."""

from django.conf import settings

from scoped.contrib.django.middleware import ScopedContextMiddleware


class PlatformScopedContextMiddleware(ScopedContextMiddleware):
    """Allow exact exemptions in addition to pyscoped's prefix exemptions.

    A prefix exemption for ``/`` would disable scoped context for the entire
    site, so the public landing page needs an exact-path exemption instead.
    """

    def _is_exempt(self, request):
        exact_paths = getattr(settings, "SCOPED_EXEMPT_EXACT_PATHS", ())
        return request.path in exact_paths or super()._is_exempt(request)
