"""Clerk webhook event handlers — organization and membership lifecycle."""

import logging
from uuid import uuid4

from django.utils.text import slugify

from plane.core.defaults import seed_default_roles
from plane.core.models import (
    Account,
    Application,
    Membership,
    Organization,
    Permission,
    Role,
    RolePermission,
)

logger = logging.getLogger(__name__)

CLERK_ROLE_MAP = {
    "org:admin": "Admin",
    "org:member": "Developer",
}


def handle_organization_created(data):
    """Create Organization, default roles, and default application."""
    clerk_org_id = data["id"]
    name = data.get("name", "Untitled")
    slug = slugify(data.get("slug", name))

    if Organization.objects.filter(clerk_org_id=clerk_org_id).exists():
        logger.info("Organization %s already exists, skipping", clerk_org_id)
        return

    creator_id = data.get("created_by")
    owner = None
    if creator_id:
        owner = Account.objects.filter(clerk_user_id=creator_id).first()
    if owner is None:
        owner = Account.objects.create(id=uuid4().hex, clerk_user_id=creator_id)

    org = Organization.objects.create(
        id=uuid4().hex,
        name=name,
        slug=_unique_slug(slug),
        clerk_org_id=clerk_org_id,
        owner=owner,
    )

    seed_default_roles(org, Role, RolePermission, Permission)

    app = Application.objects.create(
        id=uuid4().hex,
        organization=org,
        name="Default",
        slug="default",
        is_default=True,
    )

    # Sync to pyscoped (graceful degradation)
    org.sync_to_scoped()
    app.sync_to_scoped()

    # Create Stripe Customer (graceful degradation)
    from plane.billing.stripe_client import create_customer
    create_customer(org)

    logger.info("Created organization %s (%s)", org.name, org.id)


def handle_organization_updated(data):
    """Update organization name and slug, sync to pyscoped."""
    clerk_org_id = data["id"]
    try:
        org = Organization.objects.get(clerk_org_id=clerk_org_id)
    except Organization.DoesNotExist:
        logger.warning("Organization %s not found for update", clerk_org_id)
        return

    name = data.get("name")
    slug = data.get("slug")
    if name:
        org.name = name
    if slug:
        org.slug = slugify(slug)
    org.save(update_fields=["name", "slug"])

    org.sync_to_scoped()


def handle_organization_deleted(data):
    """Archive an organization via scoped scope lifecycle."""
    clerk_org_id = data["id"]
    try:
        org = Organization.objects.get(clerk_org_id=clerk_org_id)
    except Organization.DoesNotExist:
        logger.warning("Organization %s not found for deletion", clerk_org_id)
        return

    org.archive_in_scoped()

    org.status = "archived"
    org.save(update_fields=["status"])

    org.applications.all().update(is_default=False)
    from plane.core.models import ApiKey
    ApiKey.objects.filter(application__organization=org, is_active=True).update(is_active=False)

    logger.info("Archived organization %s", org.id)


def handle_membership_created(data):
    """Create a membership linking an account to an organization."""
    org_data = data.get("organization", {})
    clerk_org_id = org_data.get("id") or data.get("organization_id")
    clerk_user_id = data.get("public_user_data", {}).get("user_id")
    clerk_role = data.get("role", "org:member")
    clerk_membership_id = data.get("id")

    if not clerk_org_id or not clerk_user_id:
        logger.warning("Membership webhook missing org or user ID")
        return

    try:
        org = Organization.objects.get(clerk_org_id=clerk_org_id)
    except Organization.DoesNotExist:
        logger.warning("Organization %s not found for membership", clerk_org_id)
        return

    account = Account.objects.filter(clerk_user_id=clerk_user_id).first()
    if account is None:
        account = Account.objects.create(id=uuid4().hex, clerk_user_id=clerk_user_id)

    if Membership.objects.filter(organization=org, account=account).exists():
        logger.info("Membership already exists for %s in %s", account.id, org.id)
        return

    role = _resolve_role(org, clerk_role, is_first_member=not org.memberships.exists())

    membership = Membership.objects.create(
        id=uuid4().hex,
        organization=org,
        account=account,
        role=role,
        clerk_membership_id=clerk_membership_id,
    )

    membership.sync_to_scoped()

    logger.info("Created membership for %s in %s as %s", account.id, org.id, role.name)


def handle_membership_updated(data):
    """Update a membership role."""
    clerk_membership_id = data.get("id")
    clerk_role = data.get("role", "org:member")

    try:
        membership = Membership.objects.select_related("organization").get(
            clerk_membership_id=clerk_membership_id,
        )
    except Membership.DoesNotExist:
        logger.warning("Membership %s not found for update", clerk_membership_id)
        return

    role_name = CLERK_ROLE_MAP.get(clerk_role, "Developer")
    try:
        role = Role.objects.get(organization=membership.organization, name=role_name)
        membership.role = role
        membership.save(update_fields=["role"])
    except Role.DoesNotExist:
        logger.warning("Role %s not found in org %s", role_name, membership.organization.id)


def handle_membership_deleted(data):
    """Remove a membership via scoped revoke + Django delete."""
    clerk_membership_id = data.get("id")
    try:
        membership = Membership.objects.select_related("organization", "account").get(
            clerk_membership_id=clerk_membership_id,
        )
    except Membership.DoesNotExist:
        return

    membership.revoke_in_scoped()
    membership.delete()
    logger.info("Deleted membership %s", clerk_membership_id)


def _resolve_role(org, clerk_role, is_first_member=False):
    """Map a Clerk role string to a local Role, defaulting to Developer."""
    if is_first_member:
        role_name = "Owner"
    else:
        role_name = CLERK_ROLE_MAP.get(clerk_role, "Developer")
    try:
        return Role.objects.get(organization=org, name=role_name)
    except Role.DoesNotExist:
        return Role.objects.filter(organization=org, name="Developer").first()


def _unique_slug(base_slug):
    """Ensure slug uniqueness by appending a suffix if needed."""
    slug = base_slug
    counter = 1
    while Organization.objects.filter(slug=slug).exists():
        slug = f"{base_slug}-{counter}"
        counter += 1
    return slug
