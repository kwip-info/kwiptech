"""Test middleware that sets clerk_user + org context for dashboard view tests."""

from plane.core.models import Account


class TestClerkMiddleware:
    """Sets request.clerk_user and org context for all dashboard requests."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.clerk_user = None
        request.clerk_user_id = None
        request.organization = None
        request.membership = None
        request.permissions = set()

        if request.path.startswith("/dashboard/"):
            account, _ = Account.objects.get_or_create(
                id="test_account",
                defaults={"email": "test@test.com", "clerk_user_id": "test_clerk_user"},
            )
            request.clerk_user = account
            request.clerk_user_id = "test_clerk_user"

            org, membership = _ensure_test_org(account)
            request.organization = org
            request.membership = membership
            if membership:
                from plane.auth.middleware import _resolve_effective_role
                effective_role = _resolve_effective_role(request, membership)
                request.effective_role = effective_role
                request.permissions = set(
                    effective_role.permissions.values_list("id", flat=True)
                )

        return self.get_response(request)


def _ensure_test_org(account):
    """Create test org with Owner role and all permissions."""
    from plane.core.defaults import seed_default_roles, seed_permissions
    from plane.core.models import (
        Application,
        Membership,
        Organization,
        Permission,
        Role,
        RolePermission,
    )

    seed_permissions(Permission)

    org, org_created = Organization.objects.get_or_create(
        id="test_org",
        defaults={
            "name": "Test Org",
            "slug": "test-org",
            "owner": account,
            "is_personal": True,
        },
    )

    if org_created:
        seed_default_roles(org, Role, RolePermission, Permission)
        Application.objects.create(
            id="test_app",
            organization=org,
            name="Test App",
            slug="test-app",
            is_default=True,
        )

    owner_role = org.roles.filter(name="Owner").first()
    if owner_role is None:
        return org, None

    membership, _ = Membership.objects.get_or_create(
        organization=org,
        account=account,
        defaults={"id": "test_membership", "role": owner_role},
    )
    return org, membership
