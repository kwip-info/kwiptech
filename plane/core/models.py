"""Core models — accounts, API keys, synced audit metadata.

These models store management plane data. The customer's actual data
stays in their database — we only receive structural metadata via
the sync agent.
"""

import secrets

from django.db import models
from django.utils import timezone


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

    class Meta:
        db_table = "accounts"

    def __str__(self):
        return self.email or self.id

    @property
    def personal_organization(self):
        return self.owned_organizations.filter(is_personal=True).first()


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

    def __str__(self):
        return self.name


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
    """A named set of permissions within an organization."""

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
