"""Core models — accounts, API keys, synced audit metadata.

These models store management plane data. The customer's actual data
stays in their database — we only receive structural metadata via
the sync agent.

Models with pyscoped integration (Organization, Application, Membership,
Role) override ``save()`` and ``delete()`` to automatically sync with
the pyscoped SDK. Sync is additive — if the scoped backend is
unavailable, Django models still work.
"""

import secrets

from django.db import models, transaction
from django.utils import timezone
from scoped.logging import get_logger

_scoped_logger = get_logger("scoped_sync")


def _get_scoped_client():
    """Return the scoped client singleton, or None if unavailable."""
    try:
        from scoped.contrib.django import get_client
        return get_client()
    except Exception:
        return None


def _get_services(client):
    """Extract the service container from a scoped client."""
    from scoped.contrib._base import build_services
    return build_services(client._backend)


# ---------------------------------------------------------------------------
# Account
# ---------------------------------------------------------------------------


class Account(models.Model):
    """A pyscoped customer account (person)."""

    id = models.CharField(max_length=64, primary_key=True)
    email = models.EmailField(unique=True, null=True, blank=True)
    clerk_user_id = models.CharField(
        max_length=255,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
    )
    status = models.CharField(max_length=32, default="active")
    created_at = models.DateTimeField(default=timezone.now)

    @property
    def is_authenticated(self):
        """Required by DRF's IsAuthenticated permission."""
        return True

    class Meta:
        db_table = "accounts"

    def __str__(self):
        return self.email or self.id

    @property
    def personal_organization(self):
        return self.owned_organizations.filter(is_personal=True).first()


# ---------------------------------------------------------------------------
# ApiKey
# ---------------------------------------------------------------------------


class ApiKey(models.Model):
    """An API key belonging to an account."""

    id = models.CharField(max_length=64, primary_key=True)
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="api_keys")
    application = models.ForeignKey(
        "Application",
        on_delete=models.CASCADE,
        related_name="api_keys",
        null=True,
        blank=True,
    )
    key_hash = models.CharField(max_length=128, unique=True, db_index=True)
    key_prefix = models.CharField(max_length=20)
    environment = models.CharField(max_length=10, choices=[("live", "Live"), ("test", "Test")])
    label = models.CharField(max_length=128, blank=True, default="")
    scoped_object_id = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        db_index=True,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "api_keys"
        indexes = [
            models.Index(fields=["account", "is_active"]),
            models.Index(fields=["application", "is_active", "environment"]),
        ]

    def __str__(self):
        return f"{self.key_prefix}... ({self.environment})"

    @staticmethod
    def generate_key(environment: str = "live") -> tuple[str, str]:
        """Generate a new API key. Returns (full_key, key_hash).

        The full key is returned once and never stored.
        Only the hash is persisted for authentication.
        """
        import hashlib

        raw = secrets.token_hex(16)
        full_key = f"psc_{environment}_{raw}"
        key_hash = hashlib.sha256(full_key.encode()).hexdigest()
        return full_key, key_hash

    @staticmethod
    def hash_key(api_key: str) -> str:
        """Hash an API key for lookup."""
        import hashlib

        return hashlib.sha256(api_key.encode()).hexdigest()


# ---------------------------------------------------------------------------
# SyncedAuditEntry / SyncBatchRecord
# ---------------------------------------------------------------------------


class SyncedAuditEntry(models.Model):
    """An audit entry received from a customer's sync agent.

    Contains structural metadata only — never data payloads.
    Maps to ``SyncEntryMetadata`` from the SDK contract.
    """

    id = models.CharField(max_length=64, primary_key=True)
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="audit_entries")
    sequence = models.IntegerField(db_index=True)
    actor_id = models.CharField(max_length=64)
    action = models.CharField(max_length=64)
    target_type = models.CharField(max_length=128)
    target_id = models.CharField(max_length=64)
    timestamp = models.DateTimeField()
    hash = models.CharField(max_length=128)
    previous_hash = models.CharField(max_length=128, blank=True, default="")
    scope_id = models.CharField(max_length=64, null=True, blank=True)
    parent_trace_id = models.CharField(max_length=64, null=True, blank=True)
    metadata_json = models.JSONField(default=dict, blank=True)
    batch_id = models.CharField(max_length=64, db_index=True)
    received_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "synced_audit_entries"
        unique_together = [("account", "sequence")]
        indexes = [
            models.Index(fields=["account", "actor_id"]),
            models.Index(fields=["account", "target_type", "target_id"]),
            models.Index(fields=["account", "timestamp"]),
        ]

    def __str__(self):
        return f"[{self.sequence}] {self.action} {self.target_type}:{self.target_id}"


class SyncBatchRecord(models.Model):
    """Record of a received sync batch — for deduplication and auditing."""

    id = models.CharField(max_length=64, primary_key=True)
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="sync_batches")
    first_sequence = models.IntegerField()
    last_sequence = models.IntegerField()
    chain_hash = models.CharField(max_length=128)
    content_hash = models.CharField(max_length=128)
    signature = models.CharField(max_length=128)
    entry_count = models.IntegerField()
    sdk_version = models.CharField(max_length=20)
    received_at = models.DateTimeField(default=timezone.now)
    accepted = models.BooleanField(default=True)

    class Meta:
        db_table = "sync_batch_records"
        indexes = [
            models.Index(fields=["account", "last_sequence"]),
        ]

    def __str__(self):
        return f"Batch {self.id[:8]} seq {self.first_sequence}-{self.last_sequence}"


# ---------------------------------------------------------------------------
# Organization — syncs as pyscoped Principal (kind="org") + top-level Scope
# ---------------------------------------------------------------------------


class Organization(models.Model):
    """A team or company that owns applications and API keys."""

    id = models.CharField(max_length=64, primary_key=True)
    name = models.CharField(max_length=128)
    slug = models.SlugField(max_length=128, unique=True)
    clerk_org_id = models.CharField(
        max_length=255,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
    )
    is_personal = models.BooleanField(default=False)
    owner = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name="owned_organizations",
    )
    plan = models.CharField(max_length=32, default="free")
    stripe_customer_id = models.CharField(
        max_length=255, unique=True, null=True, blank=True, db_index=True,
    )
    stripe_subscription_id = models.CharField(
        max_length=255, null=True, blank=True,
    )
    billing_status = models.CharField(max_length=32, default="active")
    scoped_principal_id = models.CharField(max_length=64, null=True, blank=True)
    scoped_scope_id = models.CharField(max_length=64, null=True, blank=True)
    status = models.CharField(max_length=32, default="active")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "organizations"
        indexes = [
            models.Index(fields=["plan", "billing_status"]),
        ]

    def __str__(self):
        return self.name

    # -- Scoped sync -------------------------------------------------------

    def sync_to_scoped(self, *, updated_by: str = "system") -> None:
        """Create or update the pyscoped Principal + Scope for this org.

        Called automatically after save(). Safe to call manually for
        retry/repair.
        """
        client = _get_scoped_client()
        if client is None:
            return

        try:
            services = _get_services(client)
            with transaction.atomic():
                if not self.scoped_principal_id:
                    # First sync — create principal + scope
                    principal = services["principals"].create_principal(
                        kind="org",
                        display_name=self.name,
                        created_by="system",
                        principal_id=self.id,
                    )
                    scope = services["scopes"].create_scope(
                        name=self.slug,
                        owner_id=principal.id,
                        description=f"Organization: {self.name}",
                    )
                    Organization.objects.filter(pk=self.pk).update(
                        scoped_principal_id=principal.id,
                        scoped_scope_id=scope.id,
                    )
                    self.scoped_principal_id = principal.id
                    self.scoped_scope_id = scope.id
                else:
                    # Subsequent sync — update principal + scope
                    services["principals"].update_principal(
                        self.scoped_principal_id,
                        display_name=self.name,
                        updated_by=updated_by,
                    )
                    services["scopes"].rename_scope(
                        self.scoped_scope_id,
                        new_name=self.slug,
                        renamed_by=updated_by,
                    )
                    services["scopes"].update_scope(
                        self.scoped_scope_id,
                        description=f"Organization: {self.name}",
                        updated_by=updated_by,
                    )
        except Exception:
            _scoped_logger.warning("Failed to sync org to scoped", org_id=self.id)

    def archive_in_scoped(self, *, archived_by: str = "system") -> None:
        """Archive the org's pyscoped scope."""
        if not self.scoped_scope_id:
            return
        client = _get_scoped_client()
        if client is None:
            return
        try:
            services = _get_services(client)
            services["scopes"].archive_scope(
                self.scoped_scope_id,
                archived_by=archived_by,
            )
        except Exception:
            _scoped_logger.warning("Failed to archive scoped scope for org", org_id=self.id)


# ---------------------------------------------------------------------------
# Application — syncs as a child Scope under the org's scope
# ---------------------------------------------------------------------------


class Application(models.Model):
    """An application within an organization — the customer's product."""

    id = models.CharField(max_length=64, primary_key=True)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="applications",
    )
    name = models.CharField(max_length=128)
    slug = models.SlugField(max_length=128)
    scoped_scope_id = models.CharField(max_length=64, null=True, blank=True)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "applications"
        unique_together = [("organization", "slug")]

    def __str__(self):
        return f"{self.name} ({self.organization.name})"

    # -- Scoped sync -------------------------------------------------------

    def sync_to_scoped(self, *, updated_by: str = "system") -> None:
        """Create or update the pyscoped child Scope for this app.

        Called automatically after save(). Safe to call manually.
        """
        org = self.organization
        if not org.scoped_scope_id:
            return
        client = _get_scoped_client()
        if client is None:
            return

        try:
            services = _get_services(client)
            with transaction.atomic():
                if not self.scoped_scope_id:
                    scope = services["scopes"].create_scope(
                        name=self.slug,
                        owner_id=org.scoped_principal_id,
                        parent_scope_id=org.scoped_scope_id,
                        description=f"Application: {self.name}",
                    )
                    Application.objects.filter(pk=self.pk).update(
                        scoped_scope_id=scope.id,
                    )
                    self.scoped_scope_id = scope.id
                else:
                    services["scopes"].rename_scope(
                        self.scoped_scope_id,
                        new_name=self.slug,
                        renamed_by=updated_by,
                    )
                    services["scopes"].update_scope(
                        self.scoped_scope_id,
                        description=f"Application: {self.name}",
                        updated_by=updated_by,
                    )
        except Exception:
            _scoped_logger.warning("Failed to sync app to scoped", app_id=self.id)

    def archive_in_scoped(self, *, archived_by: str = "system") -> None:
        """Archive the app's pyscoped scope."""
        if not self.scoped_scope_id:
            return
        client = _get_scoped_client()
        if client is None:
            return
        try:
            services = _get_services(client)
            services["scopes"].archive_scope(
                self.scoped_scope_id,
                archived_by=archived_by,
            )
        except Exception:
            _scoped_logger.warning("Failed to archive scoped scope for app", app_id=self.id)


# ---------------------------------------------------------------------------
# Permission / Role / RolePermission
# ---------------------------------------------------------------------------


class Permission(models.Model):
    """A platform permission — reference table seeded at migration time."""

    id = models.CharField(max_length=64, primary_key=True)
    name = models.CharField(max_length=128)
    category = models.CharField(max_length=32)
    description = models.CharField(max_length=256)

    class Meta:
        db_table = "permissions"
        ordering = ["category", "id"]

    def __str__(self):
        return self.id


class Role(models.Model):
    """A named set of permissions within an organization.

    Syncs as pyscoped ACCESS rules — one rule per permission, bound to
    the org's scope.
    """

    id = models.CharField(max_length=64, primary_key=True)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="roles",
    )
    name = models.CharField(max_length=64)
    is_default = models.BooleanField(default=False)
    permissions = models.ManyToManyField(
        Permission,
        through="RolePermission",
        related_name="roles",
    )
    scoped_rule_ids = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "roles"
        unique_together = [("organization", "name")]

    def __str__(self):
        return f"{self.name} ({self.organization.name})"

    # -- Scoped sync -------------------------------------------------------

    def sync_rules_to_scoped(self, *, created_by: str = "system") -> None:
        """Create pyscoped ACCESS rules for this role's permissions.

        Archives any existing rules first, then creates fresh ones.
        """
        org = self.organization
        if not org.scoped_scope_id:
            return
        client = _get_scoped_client()
        if client is None:
            return

        try:
            from scoped.rules.models import BindingTargetType, RuleEffect, RuleType
            services = _get_services(client)

            # Archive old rules
            for rule_id in self.scoped_rule_ids or []:
                try:
                    services["rules"].archive_rule(rule_id, archived_by=created_by)
                except Exception:
                    pass

            # Create new rules
            rule_ids = []
            for perm in self.permissions.all():
                rule = services["rules"].create_rule(
                    name=f"{org.slug}:{self.name}:{perm.id}",
                    rule_type=RuleType.ACCESS,
                    effect=RuleEffect.ALLOW,
                    conditions={"action": perm.id, "role": self.name.lower()},
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

            Role.objects.filter(pk=self.pk).update(scoped_rule_ids=rule_ids)
            self.scoped_rule_ids = rule_ids
        except Exception:
            _scoped_logger.warning("Failed to sync rules for role", role_name=self.name)

    def archive_rules_in_scoped(self, *, archived_by: str = "system") -> None:
        """Archive all pyscoped rules for this role."""
        if not self.scoped_rule_ids:
            return
        client = _get_scoped_client()
        if client is None:
            return
        try:
            services = _get_services(client)
            for rule_id in self.scoped_rule_ids:
                try:
                    services["rules"].archive_rule(rule_id, archived_by=archived_by)
                except Exception:
                    pass
        except Exception:
            _scoped_logger.warning("Failed to archive scoped rules for role", role_name=self.name)


class RolePermission(models.Model):
    """Through table linking roles to permissions."""

    role = models.ForeignKey(
        Role,
        on_delete=models.CASCADE,
        related_name="role_permissions",
    )
    permission = models.ForeignKey(
        Permission,
        on_delete=models.CASCADE,
        related_name="role_permissions",
    )

    class Meta:
        db_table = "role_permissions"
        unique_together = [("role", "permission")]

    def __str__(self):
        return f"{self.role.name} -> {self.permission.id}"


# ---------------------------------------------------------------------------
# Membership — syncs as a pyscoped ScopeMembership
# ---------------------------------------------------------------------------

# Maps platform role names to pyscoped ScopeRole values
_ROLE_MAP = {
    "Owner": "owner",
    "Admin": "admin",
    "Developer": "editor",
    "Viewer": "viewer",
}


class Membership(models.Model):
    """An account's membership in an organization with a specific role."""

    id = models.CharField(max_length=64, primary_key=True)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    role = models.ForeignKey(
        Role,
        on_delete=models.PROTECT,
        related_name="memberships",
    )
    clerk_membership_id = models.CharField(
        max_length=255,
        unique=True,
        null=True,
        blank=True,
    )
    scoped_membership_id = models.CharField(max_length=64, null=True, blank=True)
    joined_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "memberships"
        unique_together = [("organization", "account")]

    def __str__(self):
        return f"{self.account} in {self.organization.name} as {self.role.name}"

    # -- Scoped sync -------------------------------------------------------

    def sync_to_scoped(self) -> None:
        """Add this member to the org's pyscoped scope.

        Called after save(). Safe to call manually.
        """
        org = self.organization
        if not org.scoped_scope_id:
            return
        client = _get_scoped_client()
        if client is None:
            return

        try:
            from scoped.tenancy.models import ScopeRole
            services = _get_services(client)

            account_principal = services["principals"].find_principal(
                self.account.id,
            )
            if account_principal is None:
                return

            role_map = {
                "Owner": ScopeRole.OWNER,
                "Admin": ScopeRole.ADMIN,
                "Developer": ScopeRole.EDITOR,
                "Viewer": ScopeRole.VIEWER,
            }
            scoped_role = role_map.get(self.role.name, ScopeRole.VIEWER)

            sm = services["scopes"].add_member(
                org.scoped_scope_id,
                principal_id=account_principal.id,
                role=scoped_role,
                granted_by=org.scoped_principal_id or "system",
            )

            Membership.objects.filter(pk=self.pk).update(
                scoped_membership_id=sm.id,
            )
            self.scoped_membership_id = sm.id
        except Exception:
            _scoped_logger.warning(
                "Failed to sync membership to scoped",
                account_id=self.account_id, org_id=self.organization_id,
            )

    @staticmethod
    def bulk_sync_to_scoped(memberships, org) -> None:
        """Add multiple members to the org scope in one call."""
        if not org.scoped_scope_id:
            return
        client = _get_scoped_client()
        if client is None:
            return

        try:
            services = _get_services(client)
            members = []
            for m in memberships:
                principal = services["principals"].find_principal(m.account.id)
                if principal is None:
                    continue
                members.append({
                    "principal_id": principal.id,
                    "role": _ROLE_MAP.get(m.role.name, "viewer"),
                })

            if members:
                results = services["scopes"].add_members(
                    org.scoped_scope_id,
                    members=members,
                    granted_by=org.scoped_principal_id or "system",
                )
                for m, sm in zip(memberships, results):
                    Membership.objects.filter(pk=m.pk).update(
                        scoped_membership_id=sm.id,
                    )
                    m.scoped_membership_id = sm.id
        except Exception:
            _scoped_logger.warning(
                "Failed to bulk sync memberships", org_id=org.id,
            )

    def revoke_in_scoped(self, *, revoked_by: str = "system") -> None:
        """Revoke this member from the org's pyscoped scope."""
        org = self.organization
        if not org.scoped_scope_id or not self.scoped_membership_id:
            return
        client = _get_scoped_client()
        if client is None:
            return
        try:
            services = _get_services(client)
            account_principal = services["principals"].find_principal(
                self.account.id,
            )
            if account_principal:
                services["scopes"].revoke_member(
                    org.scoped_scope_id,
                    principal_id=account_principal.id,
                    revoked_by=revoked_by,
                )
        except Exception:
            _scoped_logger.warning(
                "Failed to revoke scoped membership",
                account_id=self.account_id, org_id=org.id,
            )
