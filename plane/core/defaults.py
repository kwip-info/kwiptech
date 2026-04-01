"""Default permissions and roles for new organizations.

Used by both the migration seed and runtime provisioning
(webhook handlers, personal org auto-creation).
"""

PERMISSIONS = [
    ("keys.view", "View API keys", "keys", "View API keys and their metadata"),
    ("keys.create", "Create API keys", "keys", "Create new API keys"),
    ("keys.revoke", "Revoke API keys", "keys", "Revoke active API keys"),
    ("keys.rotate", "Rotate API keys", "keys", "Rotate API keys to new credentials"),
    ("audit.view", "View audit trail", "audit", "View the platform audit trail"),
    ("apps.view", "View applications", "apps", "View applications and their settings"),
    ("apps.create", "Create applications", "apps", "Create new applications"),
    ("apps.manage", "Manage applications", "apps", "Edit and delete applications"),
    ("members.view", "View members", "members", "View organization members"),
    ("members.manage", "Manage members", "members", "Invite and remove members, change roles"),
    ("roles.view", "View roles", "roles", "View roles and their permissions"),
    ("roles.manage", "Manage roles", "roles", "Create, edit, and delete custom roles"),
    ("billing.view", "View billing", "billing", "View billing information and usage"),
    ("billing.manage", "Manage billing", "billing", "Update billing settings and plan"),
]

DEFAULT_ROLES = {
    "Owner": [p[0] for p in PERMISSIONS],
    "Admin": [p[0] for p in PERMISSIONS if p[0] != "billing.manage"],
    "Developer": [
        "keys.view", "keys.create", "keys.revoke", "keys.rotate",
        "audit.view", "apps.view",
    ],
    "Viewer": [
        "keys.view", "audit.view", "apps.view",
        "members.view", "roles.view", "billing.view",
    ],
}


def seed_permissions(Permission):
    """Create all Permission rows. Idempotent."""
    for perm_id, name, category, description in PERMISSIONS:
        Permission.objects.get_or_create(
            id=perm_id,
            defaults={
                "name": name,
                "category": category,
                "description": description,
            },
        )


def seed_default_roles(organization, Role, RolePermission, Permission):
    """Create default roles for an organization. Idempotent.

    Accepts model classes so this works from both migrations
    (where you must use apps.get_model) and runtime code.
    """
    for role_name, perm_ids in DEFAULT_ROLES.items():
        role, created = Role.objects.get_or_create(
            organization=organization,
            name=role_name,
            defaults={
                "id": f"{organization.id}_{role_name.lower()}",
                "is_default": True,
            },
        )
        if created:
            perms = Permission.objects.filter(id__in=perm_ids)
            for perm in perms:
                RolePermission.objects.get_or_create(role=role, permission=perm)
