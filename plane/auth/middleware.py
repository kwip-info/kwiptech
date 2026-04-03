"""Clerk authentication middleware for dashboard requests."""

from django.shortcuts import redirect
from scoped.logging import get_logger

from plane.auth.jwt import JwtVerificationError, verify_clerk_token
from plane.auth.services import get_or_create_account

logger = get_logger("plane.auth.middleware")

PROTECTED_PREFIXES = ("/dashboard/",)
SKIP_PREFIXES = ("/admin/", "/v1/", "/static/", "/webhooks/")
SIGN_IN_URL = "/sign-in"


class ClerkAuthMiddleware:
    """Verify Clerk JWT on requests.

    Protected paths (/dashboard/) redirect to sign-in if unauthenticated.
    Public paths try to authenticate (for navbar state) but never redirect.
    Skipped paths (admin, API, static) are ignored entirely.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.clerk_user = None
        request.clerk_user_id = None
        request.organization = None
        request.membership = None
        request.permissions = set()

        if _should_skip(request.path):
            return self.get_response(request)

        token = _extract_token(request)
        is_protected = _is_protected(request.path)

        if not token:
            if is_protected:
                return redirect(SIGN_IN_URL)
            return self.get_response(request)

        try:
            claims = verify_clerk_token(token)
        except JwtVerificationError:
            logger.debug(f"Clerk JWT verification failed for {request.path}")
            if is_protected:
                response = redirect(SIGN_IN_URL)
                response.delete_cookie("__session")
                return response
            return self.get_response(request)

        request.clerk_user_id = claims["sub"]
        request.clerk_user = get_or_create_account(claims["sub"], claims)

        if request.clerk_user:
            _resolve_org_context(request, claims)

        return self.get_response(request)


def _should_skip(path):
    return any(path.startswith(prefix) for prefix in SKIP_PREFIXES)


def _is_protected(path):
    return any(path.startswith(prefix) for prefix in PROTECTED_PREFIXES)


def _extract_token(request):
    """Extract Clerk JWT from cookie or Authorization header."""
    for name, value in request.COOKIES.items():
        if name == "__session" or name.startswith("__session_"):
            return value

    auth = request.META.get("HTTP_AUTHORIZATION", "")
    if auth.startswith("Bearer ") and not auth[7:].startswith("psc_"):
        return auth[7:].strip()

    return None


def _resolve_org_context(request, claims):
    """Resolve organization, membership, and permissions from JWT claims."""
    from plane.core.models import Membership, Organization

    account = request.clerk_user

    # Clerk puts org info in the "o" claim when an org is active
    org_claim = claims.get("o")
    if org_claim and org_claim.get("id"):
        request.organization = (
            Organization.objects
            .filter(clerk_org_id=org_claim["id"], status="active")
            .first()
        )
    else:
        request.organization = account.personal_organization

    if request.organization is None:
        return

    membership = (
        Membership.objects
        .filter(organization=request.organization, account=account)
        .select_related("role")
        .first()
    )
    if membership:
        request.membership = membership
        effective_role = _resolve_effective_role(request, membership)
        request.effective_role = effective_role
        request.permissions = set(
            effective_role.permissions.values_list("id", flat=True)
        )


def _resolve_effective_role(request, membership):
    """Return the effective role considering app+env overrides.

    Resolution order:
    1. Exact match: (membership, active_app, active_env)
    2. App-wide:    (membership, active_app, env=NULL)
    3. Org-level:   membership.role  (fallback)
    """
    from plane.core.models import AppMembership, Application

    org = request.organization
    if org is None:
        return membership.role

    # Read active app from cookie
    app_id = request.COOKIES.get("scoped_app")
    active_app = None
    if app_id:
        try:
            active_app = org.applications.get(id=app_id)
        except Application.DoesNotExist:
            pass
    if active_app is None:
        active_app = org.applications.filter(is_default=True).first()

    if active_app is None:
        return membership.role

    # Read active env from cookie
    active_env = request.COOKIES.get("scoped_env", "test")
    if active_env not in ("test", "live"):
        active_env = "test"

    # Step 1: exact (app, env) override
    override = (
        AppMembership.objects
        .filter(membership=membership, application=active_app, environment=active_env)
        .select_related("role")
        .first()
    )
    if override:
        return override.role

    # Step 2: app-wide override (env=NULL)
    override = (
        AppMembership.objects
        .filter(membership=membership, application=active_app, environment__isnull=True)
        .select_related("role")
        .first()
    )
    if override:
        return override.role

    # Step 3: fallback to org-level
    return membership.role
