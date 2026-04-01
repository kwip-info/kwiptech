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

import logging

from plane.dashboard.scoped import scoped_operation

logger = logging.getLogger(__name__)


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
        logger.warning("Failed to create scoped objects for org %s", org.id, exc_info=True)


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
        logger.warning("Failed to archive scoped scope for org %s", org.id, exc_info=True)


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
        logger.warning("Failed to create scoped scope for app %s", app.id, exc_info=True)


def update_app_in_scoped(app, updated_by="system"):
    """Record an app rename via scope_modify audit entry.

    The SDK doesn't have a scope rename method yet, so we write
    the audit entry directly. This is the one place we do this —
    everywhere else uses native SDK operations.
    """
    if not app.scoped_scope_id:
        return
    try:
        with scoped_operation() as client:
            from scoped.types import ActionType
            services = _get_services(client)
            services["audit_writer"].record(
                actor_id=updated_by,
                action=ActionType.SCOPE_MODIFY,
                target_type="Scope",
                target_id=app.scoped_scope_id,
                scope_id=app.scoped_scope_id,
                after_state={"name": app.name, "slug": app.slug},
            )
    except Exception:
        logger.warning("Failed to record scope modify for app %s", app.id, exc_info=True)


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
        logger.warning("Failed to archive scoped scope for app %s", app.id, exc_info=True)


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
            "Failed to create scoped membership for %s in org %s",
            membership.account.id, membership.organization.id, exc_info=True,
        )


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
            "Failed to revoke scoped membership for %s in org %s",
            membership.account.id, org.id, exc_info=True,
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
        logger.warning(
            "Failed to create scoped rules for role %s", role.name, exc_info=True,
        )


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
        logger.warning(
            "Failed to update scoped rules for role %s", role.name, exc_info=True,
        )


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
        logger.warning(
            "Failed to archive scoped rules for role %s", role.name, exc_info=True,
        )
