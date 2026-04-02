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
        request.permissions = set(
            membership.role.permissions.values_list("id", flat=True)
        )
