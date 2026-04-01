"""Template tags for the dashboard."""

from django import template

register = template.Library()

ENV_COOKIE = "scoped_env"
DEFAULT_ENV = "test"


@register.simple_tag(takes_context=True)
def active_env(context):
    """Return the active environment from the scoped_env cookie."""
    request = context.get("request")
    if request is None:
        return DEFAULT_ENV
    return request.COOKIES.get(ENV_COOKIE, DEFAULT_ENV)


@register.simple_tag(takes_context=True)
def nav_active(context, path_prefix):
    """Return CSS classes for active sidebar link."""
    request = context.get("request")
    if request and request.path.startswith(path_prefix):
        return "bg-white text-gray-900 shadow-sm"
    return "text-gray-600 hover:bg-white hover:text-gray-900"


@register.simple_tag(takes_context=True)
def has_perm(context, permission_id):
    """Check if the current user has a specific permission."""
    permissions = context.get("permissions", set())
    return permission_id in permissions
