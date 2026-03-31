"""Core models — accounts, API keys, synced audit metadata.

These models store management plane data. The customer's actual data
stays in their database — we only receive structural metadata via
the sync agent.
"""

import secrets

from django.db import models
from django.utils import timezone


class Account(models.Model):
    """A pyscoped customer account."""

    id = models.CharField(max_length=64, primary_key=True)
    email = models.EmailField(unique=True)
    plan = models.CharField(max_length=32, default="free")
    status = models.CharField(max_length=32, default="active")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "accounts"

    def __str__(self):
        return f"{self.email} ({self.plan})"


class ApiKey(models.Model):
    """An API key belonging to an account."""

    id = models.CharField(max_length=64, primary_key=True)
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name="api_keys")
    key_hash = models.CharField(max_length=128, unique=True, db_index=True)
    key_prefix = models.CharField(max_length=20)
    environment = models.CharField(max_length=10, choices=[("live", "Live"), ("test", "Test")])
    label = models.CharField(max_length=128, blank=True, default="")
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
