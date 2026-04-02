"""Billing models — usage snapshots and plan tracking.

Usage-based billing. Active objects and principals are metered via
peak counts per billing period. The sync agent pushes resource counts
with every batch.
"""

from django.db import models
from django.utils import timezone


class StripeEvent(models.Model):
    """Tracks processed Stripe webhook events for idempotency.

    Before processing any webhook, we check if the event ID has already
    been recorded. If so, we skip processing to prevent double state changes.
    """

    id = models.CharField(max_length=255, primary_key=True)  # Stripe event ID (evt_...)
    event_type = models.CharField(max_length=128)
    processed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "stripe_events"

    def __str__(self):
        return f"{self.event_type} ({self.id})"


class Plan(models.Model):
    """A billing plan tier with Stripe price mappings."""

    id = models.CharField(max_length=32, primary_key=True)
    name = models.CharField(max_length=64)
    max_objects = models.IntegerField()
    max_principals = models.IntegerField()
    audit_retention_days = models.IntegerField()
    min_sync_interval_seconds = models.IntegerField()
    price_cents_monthly = models.IntegerField(default=0)

    # Stripe Price IDs (populated after Stripe Products are created)
    stripe_base_price_id = models.CharField(max_length=255, blank=True, default="")
    stripe_object_price_id = models.CharField(max_length=255, blank=True, default="")
    stripe_principal_price_id = models.CharField(max_length=255, blank=True, default="")

    # Included allowances (overage above these is metered)
    included_objects = models.IntegerField(default=0)
    included_principals = models.IntegerField(default=0)
    overage_per_object_cents = models.IntegerField(default=0)
    overage_per_principal_cents = models.IntegerField(default=0)

    class Meta:
        db_table = "plans"

    def __str__(self):
        return self.name


class UsageSnapshot(models.Model):
    """Point-in-time resource counts from a sync batch.

    Peak values over a billing period determine the bill.
    """

    id = models.BigAutoField(primary_key=True)
    account = models.ForeignKey(
        "core.Account", on_delete=models.CASCADE, related_name="usage_snapshots"
    )
    organization = models.ForeignKey(
        "core.Organization",
        on_delete=models.CASCADE,
        related_name="usage_snapshots",
        null=True,
        blank=True,
    )
    application = models.ForeignKey(
        "core.Application",
        on_delete=models.CASCADE,
        related_name="usage_snapshots",
        null=True,
        blank=True,
    )
    active_objects = models.IntegerField()
    active_principals = models.IntegerField()
    active_scopes = models.IntegerField()
    audit_entries_synced = models.IntegerField(default=0)
    recorded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "usage_snapshots"
        indexes = [
            models.Index(fields=["account", "recorded_at"]),
        ]

    def __str__(self):
        return f"{self.account_id} @ {self.recorded_at}: {self.active_objects} obj"


class BillingPeriod(models.Model):
    """A billing period with peak usage tracked."""

    id = models.BigAutoField(primary_key=True)
    account = models.ForeignKey(
        "core.Account", on_delete=models.CASCADE, related_name="billing_periods"
    )
    organization = models.ForeignKey(
        "core.Organization",
        on_delete=models.CASCADE,
        related_name="billing_periods",
        null=True,
        blank=True,
    )
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    peak_objects = models.IntegerField(default=0)
    peak_principals = models.IntegerField(default=0)
    total_audit_entries = models.IntegerField(default=0)
    finalized = models.BooleanField(default=False)
    close_attempts = models.IntegerField(default=0)
    close_error = models.TextField(blank=True, default="")

    class Meta:
        db_table = "billing_periods"
        indexes = [
            models.Index(fields=["account", "period_start"]),
        ]

    def __str__(self):
        return f"{self.account_id} {self.period_start.date()} - {self.period_end.date()}"
