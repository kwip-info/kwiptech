"""Dual-model sync — scoped lifecycle operations for Django models.

Every Organization, Application, Membership, and Role has a Django
model (fast lookup projection) and a scoped counterpart (authoritative
lifecycle record). This module bridges the two using the SDK's native
operations — create_scope, archive_scope, add_member, create_rule, etc.

The scoped layer handles audit entries, versioning, and hash chaining
automatically. We never write audit entries directly.

All functions use try/except with logging — scoped integration is
additive, never blocking. If the scoped backend is unavailable,
Django models still work.
"""

from scoped.logging import get_logger

from plane.dashboard.scoped import scoped_operation

logger = get_logger("scoped_sync")


def _get_services(client):
    from scoped.contrib._base import build_services
    return build_services(client._backend)


# -- Organizations --------------------------------------------------------

def create_org_in_scoped(org):
    """Create a scoped principal (kind: org) and top-level scope."""
    try:
        with scoped_operation() as client:
            services = _get_services(client)

            principal = services["principals"].create_principal(
                kind="org",
                display_name=org.name,
                created_by="system",
                principal_id=org.id,
            )

            scope = services["scopes"].create_scope(
                name=org.slug,
                owner_id=principal.id,
                description=f"Organization: {org.name}",
            )

            org.scoped_principal_id = principal.id
            org.scoped_scope_id = scope.id
            org.save(update_fields=["scoped_principal_id", "scoped_scope_id"])
    except Exception:
        logger.warning("Failed to create scoped objects for org", org_id=org.id)


def update_org_in_scoped(org, updated_by="system"):
    """Update the org's scoped principal display_name and scope name/description."""
    if not org.scoped_scope_id:
        return
    try:
        with scoped_operation() as client:
            services = _get_services(client)
            # Update principal display_name
            if org.scoped_principal_id:
                services["principals"].update_principal(
                    org.scoped_principal_id,
                    display_name=org.name,
                    updated_by=updated_by,
                )
            # Update scope name + description
            services["scopes"].rename_scope(
                org.scoped_scope_id,
                new_name=org.slug,
                renamed_by=updated_by,
            )
            services["scopes"].update_scope(
                org.scoped_scope_id,
                description=f"Organization: {org.name}",
                updated_by=updated_by,
            )
    except Exception:
        logger.warning("Failed to update scoped objects for org", org_id=org.id)


def archive_org_in_scoped(org, archived_by="system"):
    """Archive the org scope via ScopeLifecycle.archive_scope."""
    if not org.scoped_scope_id:
        return
    try:
        with scoped_operation() as client:
            services = _get_services(client)
            services["scopes"].archive_scope(
                org.scoped_scope_id,
                archived_by=archived_by,
            )
    except Exception:
        logger.warning("Failed to archive scoped scope for org", org_id=org.id)


# -- Applications (scoped Scopes) -----------------------------------------

def create_app_in_scoped(app):
    """Create a child scope for an application under its org scope."""
    if not app.organization.scoped_scope_id:
        return
    try:
        with scoped_operation() as client:
            services = _get_services(client)

            scope = services["scopes"].create_scope(
                name=app.slug,
                owner_id=app.organization.scoped_principal_id,
                parent_scope_id=app.organization.scoped_scope_id,
                description=f"Application: {app.name}",
            )

            app.scoped_scope_id = scope.id
            app.save(update_fields=["scoped_scope_id"])
    except Exception:
        logger.warning("Failed to create scoped scope for app", app_id=app.id)


def update_app_in_scoped(app, updated_by="system"):
    """Rename and update the app's scope via native SDK operations."""
    if not app.scoped_scope_id:
        return
    try:
        with scoped_operation() as client:
            services = _get_services(client)
            services["scopes"].rename_scope(
                app.scoped_scope_id,
                new_name=app.slug,
                renamed_by=updated_by,
            )
            services["scopes"].update_scope(
                app.scoped_scope_id,
                description=f"Application: {app.name}",
                updated_by=updated_by,
            )
    except Exception:
        logger.warning("Failed to update scoped scope for app %s", app.id, app_id=app.id)


def archive_app_in_scoped(app, archived_by="system"):
    """Archive the app scope via ScopeLifecycle.archive_scope."""
    if not app.scoped_scope_id:
        return
    try:
        with scoped_operation() as client:
            services = _get_services(client)
            services["scopes"].archive_scope(
                app.scoped_scope_id,
                archived_by=archived_by,
            )
    except Exception:
        logger.warning("Failed to archive scoped scope for app", app_id=app.id)


# -- Memberships ----------------------------------------------------------

def create_membership_in_scoped(membership):
    """Add a member to the org scope via ScopeLifecycle.add_member."""
    org = membership.organization
    if not org.scoped_scope_id:
        return
    try:
        with scoped_operation() as client:
            from scoped.tenancy.models import ScopeRole
            services = _get_services(client)

            account_principal = services["principals"].find_principal(
                membership.account.id,
            )
            if account_principal is None:
                return

            role_map = {
                "Owner": ScopeRole.OWNER,
                "Admin": ScopeRole.ADMIN,
                "Developer": ScopeRole.EDITOR,
                "Viewer": ScopeRole.VIEWER,
            }
            scoped_role = role_map.get(membership.role.name, ScopeRole.VIEWER)

            sm = services["scopes"].add_member(
                org.scoped_scope_id,
                principal_id=account_principal.id,
                role=scoped_role,
                granted_by=org.scoped_principal_id or "system",
            )

            membership.scoped_membership_id = sm.id
            membership.save(update_fields=["scoped_membership_id"])
    except Exception:
        logger.warning(
            "Failed to create scoped membership",
            account_id=membership.account.id, org_id=membership.organization.id,
        )


def create_memberships_in_scoped(memberships, org):
    """Add multiple members to the org scope in one call via add_members."""
    if not org.scoped_scope_id:
        return
    try:
        with scoped_operation() as client:
            from scoped.tenancy.models import ScopeRole
            services = _get_services(client)

            role_map = {
                "Owner": "owner",
                "Admin": "admin",
                "Developer": "editor",
                "Viewer": "viewer",
            }

            members = []
            for m in memberships:
                principal = services["principals"].find_principal(m.account.id)
                if principal is None:
                    continue
                members.append({
                    "principal_id": principal.id,
                    "role": role_map.get(m.role.name, "viewer"),
                })

            if members:
                results = services["scopes"].add_members(
                    org.scoped_scope_id,
                    members=members,
                    granted_by=org.scoped_principal_id or "system",
                )
                # Update Django models with scoped membership IDs
                for m, sm in zip(memberships, results):
                    m.scoped_membership_id = sm.id
                    m.save(update_fields=["scoped_membership_id"])
    except Exception:
        logger.warning("Failed to bulk-create scoped memberships for org %s", org.id, org_id=org.id)


def revoke_membership_in_scoped(membership, revoked_by="system"):
    """Revoke a member from the org scope via ScopeLifecycle.revoke_member."""
    org = membership.organization
    if not org.scoped_scope_id or not membership.scoped_membership_id:
        return
    try:
        with scoped_operation() as client:
            services = _get_services(client)
            account_principal = services["principals"].find_principal(
                membership.account.id,
            )
            if account_principal:
                services["scopes"].revoke_member(
                    org.scoped_scope_id,
                    principal_id=account_principal.id,
                    revoked_by=revoked_by,
                )
    except Exception:
        logger.warning(
            "Failed to revoke scoped membership",
            account_id=membership.account.id, org_id=org.id,
        )


# -- Roles (scoped Rules) -------------------------------------------------

def create_role_rules_in_scoped(role):
    """Create scoped ACCESS rules for a role's permissions."""
    org = role.organization
    if not org.scoped_scope_id:
        return
    try:
        with scoped_operation() as client:
            from scoped.rules.models import BindingTargetType, RuleEffect, RuleType
            services = _get_services(client)

            rule_ids = []
            for perm in role.permissions.all():
                rule = services["rules"].create_rule(
                    name=f"{org.slug}:{role.name}:{perm.id}",
                    rule_type=RuleType.ACCESS,
                    effect=RuleEffect.ALLOW,
                    conditions={"action": perm.id, "role": role.name.lower()},
                    priority=100,
                    created_by=org.scoped_principal_id or "system",
                )
                services["rules"].bind_rule(
                    rule.id,
                    target_type=BindingTargetType.SCOPE,
                    target_id=org.scoped_scope_id,
                    bound_by=org.scoped_principal_id or "system",
                )
                rule_ids.append(rule.id)

            role.scoped_rule_ids = rule_ids
            role.save(update_fields=["scoped_rule_ids"])
    except Exception:
        logger.warning("Failed to create scoped rules for role", role_name=role.name)


def update_role_rules_in_scoped(role, updated_by="system"):
    """Update scoped rules when a role's permissions change.

    Archives old rules and creates new ones for the current permission set.
    Uses RuleStore.archive_rule (audited) + create_rule (audited).
    """
    org = role.organization
    if not org.scoped_scope_id:
        return
    try:
        with scoped_operation() as client:
            services = _get_services(client)

            # Archive old rules
            for rule_id in role.scoped_rule_ids or []:
                try:
                    services["rules"].archive_rule(rule_id, archived_by=updated_by)
                except Exception:
                    pass

        # Create new rules
        create_role_rules_in_scoped(role)
    except Exception:
        logger.warning("Failed to update scoped rules for role", role_name=role.name)


def archive_role_rules_in_scoped(role, archived_by="system"):
    """Archive all scoped rules for a role via RuleStore.archive_rule."""
    if not role.scoped_rule_ids:
        return
    try:
        with scoped_operation() as client:
            services = _get_services(client)
            for rule_id in role.scoped_rule_ids:
                try:
                    services["rules"].archive_rule(rule_id, archived_by=archived_by)
                except Exception:
                    pass
    except Exception:
        logger.warning("Failed to archive scoped rules for role", role_name=role.name)
