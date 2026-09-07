"""Marketplace identities are separate from the retired hosted PyScoped accounts."""
import uuid
from django.db import models
from django.utils import timezone

class Identity(models.Model):
    subject = models.CharField(max_length=255, unique=True)
    active = models.BooleanField(default=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    is_operator = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

class Workspace(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.OneToOneField(Identity, on_delete=models.PROTECT, related_name='workspace')
    name = models.CharField(max_length=120, default='My workspace')
    created_at = models.DateTimeField(auto_now_add=True)

class ServiceKey(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name='keys')
    name = models.CharField(max_length=80)
    token_hash = models.CharField(max_length=64, unique=True)
    prefix = models.CharField(max_length=18)
    scopes = models.JSONField(default=list)
    dataset_slugs = models.JSONField(default=list)
    source_slugs = models.JSONField(default=list)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

class DeviceGrant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device_hash = models.CharField(max_length=64, unique=True)
    user_code = models.CharField(max_length=12, unique=True)
    name = models.CharField(max_length=80)
    scopes = models.JSONField(default=list)
    workspace = models.ForeignKey(Workspace, null=True, on_delete=models.CASCADE)
    status = models.CharField(max_length=16, default='pending')
    expires_at = models.DateTimeField()
    last_poll_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

class RateBucket(models.Model):
    """Shared, atomic fixed-window request limiter; no process-local counters."""
    key = models.CharField(max_length=64, primary_key=True)
    starts_at = models.DateTimeField(default=timezone.now)
    count = models.PositiveIntegerField(default=0)

class RevokedSession(models.Model):
    session_id = models.CharField(max_length=255, primary_key=True)
    subject = models.CharField(max_length=255, blank=True)
    revoked_at = models.DateTimeField(default=timezone.now)

class IdentityEvent(models.Model):
    message_id = models.CharField(max_length=255, primary_key=True)
    event_type = models.CharField(max_length=100)
    subject = models.CharField(max_length=255, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)

class JWKSnapshot(models.Model):
    issuer = models.CharField(max_length=255, primary_key=True)
    document = models.JSONField(default=dict)
    fetched_at = models.DateTimeField(null=True)
    last_attempt_at = models.DateTimeField(null=True)
