import uuid
from django.db import models


class BillingAccount(models.Model):
    workspace = models.OneToOneField('access.Workspace', primary_key=True, on_delete=models.PROTECT)
    stripe_customer_id = models.CharField(max_length=100, blank=True, unique=True, null=True)
    stripe_subscription_id = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=30, default='free')
    period_start = models.DateTimeField(null=True)
    period_end = models.DateTimeField(null=True)
    allowance_start = models.DateTimeField(null=True)
    overage_enabled = models.BooleanField(default=False)
    spend_cap_cents = models.PositiveIntegerField(default=0)
    metered_item_active = models.BooleanField(default=False)
    checkout_generation = models.UUIDField(default=uuid.uuid4)
    checkout_session_id = models.CharField(max_length=120, blank=True)
    checkout_url = models.URLField(max_length=2000, blank=True)
    checkout_expires_at = models.DateTimeField(null=True)
    reconciled_at = models.DateTimeField(null=True)
    cancellation_requested_at = models.DateTimeField(null=True)
    cancellation_completed_at = models.DateTimeField(null=True)


class Delivery(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey('access.Workspace', on_delete=models.PROTECT)
    dataset_slug = models.CharField(max_length=100)
    request_id = models.CharField(max_length=200)
    fingerprint = models.CharField(max_length=128)
    response = models.JSONField()
    records = models.PositiveIntegerField()
    credits = models.PositiveBigIntegerField()
    overage_credits = models.PositiveBigIntegerField(default=0)
    pricing_cents_per_10000 = models.PositiveIntegerField()
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['workspace', 'request_id'], name='commerce_unique_delivery')]
        indexes = [models.Index(fields=['workspace', 'created_at'], name='commerce_usage_period')]


class MeterOutbox(models.Model):
    delivery = models.OneToOneField(Delivery, primary_key=True, on_delete=models.PROTECT)
    customer_id = models.CharField(max_length=100)
    event_name = models.CharField(max_length=100)
    status = models.CharField(max_length=20, default='pending')
    attempts = models.PositiveIntegerField(default=0)
    first_attempt_at = models.DateTimeField(null=True)
    next_attempt_at = models.DateTimeField(null=True)
    lease_until = models.DateTimeField(null=True)
    submitted_at = models.DateTimeField(null=True)
    error_code = models.CharField(max_length=100, blank=True)


class StripeEvent(models.Model):
    event_id = models.CharField(max_length=120, primary_key=True)
    event_type = models.CharField(max_length=120)
    payload = models.JSONField()
    status = models.CharField(max_length=20, default='pending')
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True)
    error_code = models.CharField(max_length=100, blank=True)


class MeterReconciliation(models.Model):
    workspace = models.ForeignKey('access.Workspace', on_delete=models.PROTECT)
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    expected_credits = models.PositiveBigIntegerField()
    remote_credits = models.DecimalField(max_digits=24, decimal_places=6)
    status = models.CharField(max_length=20)
    checked_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['workspace', 'start_at', 'end_at'], name='commerce_unique_reconciliation')]


class BillingConsent(models.Model):
    workspace = models.ForeignKey('access.Workspace', on_delete=models.PROTECT)
    identity = models.ForeignKey('access.Identity', on_delete=models.PROTECT)
    overage_enabled = models.BooleanField()
    spend_cap_cents = models.PositiveIntegerField()
    overage_cents_per_10000 = models.PositiveIntegerField()
    policy_version = models.CharField(max_length=40, default='marketplace-v1')
    created_at = models.DateTimeField(auto_now_add=True)
