"""Account lookup and creation from Clerk JWT claims."""

from uuid import uuid4

from django.db import IntegrityError
from scoped.logging import get_logger

from plane.core.models import Account, Application, Membership, Organization

logger = get_logger("plane.auth.services")


def _fetch_clerk_email(clerk_user_id):
    """Fetch primary email from Clerk Backend API. Returns None on failure."""
    import json
    import urllib.request
    import urllib.error

    from django.conf import settings

    secret = getattr(settings, "CLERK_SECRET_KEY", None)
    if not secret:
        return None
    try:
        req = urllib.request.Request(
            f"https://api.clerk.com/v1/users/{clerk_user_id}",
            headers={
                "Authorization": f"Bearer {secret}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            # Clerk returns email_addresses array; find the primary one
            for ea in data.get("email_addresses", []):
                if ea.get("id") == data.get("primary_email_address_id"):
                    return ea.get("email_address")
            # Fallback: first email
            if data.get("email_addresses"):
                return data["email_addresses"][0].get("email_address")
    except Exception:
        logger.warning("Failed to fetch email from Clerk API", clerk_user_id=clerk_user_id)
    return None


def get_or_create_account(clerk_user_id, claims):
    """Find or create an Account for a Clerk user.

    Lookup order:
    1. By clerk_user_id (returning Clerk user)
    2. By email if present in claims (links API-provisioned account)
    3. Create new account

    Returns the Account instance.
    """
    # 1. Existing Clerk-linked account
    try:
        account = Account.objects.get(clerk_user_id=clerk_user_id)
        # Backfill email if missing (from claims or Clerk API)
        if not account.email:
            email = claims.get("email") or _fetch_clerk_email(clerk_user_id)
            if email:
                account.email = email
                account.save(update_fields=["email"])
        ensure_personal_organization(account)
        return account
    except Account.DoesNotExist:
        pass

    email = claims.get("email") or _fetch_clerk_email(clerk_user_id)

    # 2. Link existing API-provisioned account by email
    if email:
        try:
            account = Account.objects.get(email=email)
            account.clerk_user_id = clerk_user_id
            account.save(update_fields=["clerk_user_id"])
            logger.info("Linked Clerk user to existing account", clerk_user_id=clerk_user_id, account_id=account.id)
            ensure_personal_organization(account)
            return account
        except Account.DoesNotExist:
            pass

    # 3. Create new account
    try:
        account = Account.objects.create(
            id=uuid4().hex,
            email=email,
            clerk_user_id=clerk_user_id,
        )
        logger.info("Created new account", account_id=account.id, clerk_user_id=clerk_user_id)
        ensure_personal_organization(account)
        return account
    except IntegrityError:
        # Race condition: another request created the account concurrently
        return Account.objects.get(clerk_user_id=clerk_user_id)


def ensure_personal_organization(account):
    """Create a personal organization for an account if it doesn't have one.

    Personal orgs are invisible single-user workspaces created on signup.
    They get upgraded to a proper org when the user creates a Clerk org.
    """
    from plane.core.defaults import seed_default_roles
    from plane.core.models import Permission, Role, RolePermission

    org, created = Organization.objects.get_or_create(
        owner=account,
        is_personal=True,
        defaults={
            "id": uuid4().hex,
            "name": f"{account.email or 'My'} Workspace",
            "slug": f"personal-{account.id[:12]}",
        },
    )
    if not created:
        return org

    seed_default_roles(org, Role, RolePermission, Permission)

    app = Application.objects.create(
        id=uuid4().hex,
        organization=org,
        name="Default",
        slug="default",
        is_default=True,
    )

    owner_role = org.roles.get(name="Owner")
    membership = Membership.objects.create(
        id=uuid4().hex,
        organization=org,
        account=account,
        role=owner_role,
    )

    # Sync to pyscoped (graceful degradation)
    org.sync_to_scoped()
    app.sync_to_scoped()
    membership.sync_to_scoped()

    # Create Stripe Customer (graceful degradation)
    from plane.billing.stripe_client import create_customer
    create_customer(org)

    logger.info("Created personal organization", org_id=org.id, account_id=account.id)
    return org
