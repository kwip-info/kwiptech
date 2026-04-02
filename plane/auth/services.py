"""Account lookup and creation from Clerk JWT claims."""

import logging
from uuid import uuid4

from django.db import IntegrityError

from plane.core.models import Account, Application, Membership, Organization

logger = logging.getLogger(__name__)


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
        ensure_personal_organization(account)
        return account
    except Account.DoesNotExist:
        pass

    email = claims.get("email")

    # 2. Link existing API-provisioned account by email
    if email:
        try:
            account = Account.objects.get(email=email)
            account.clerk_user_id = clerk_user_id
            account.save(update_fields=["clerk_user_id"])
            logger.info("Linked Clerk user %s to existing account %s", clerk_user_id, account.id)
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
        logger.info("Created new account %s for Clerk user %s", account.id, clerk_user_id)
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

    logger.info("Created personal organization %s for account %s", org.id, account.id)
    return org
