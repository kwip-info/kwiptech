"""Billing models — usage snapshots and plan tracking.

Usage-based billing. Active objects and principals are metered via
peak counts per billing period. The sync agent pushes resource counts
with every batch.
"""

from django.db import models
from django.utils import timezone


class Plan(models.Model):
    """A billing plan tier."""

    id = models.CharField(max_length=32, primary_key=True)
    name = models.CharField(max_length=64)
    max_objects = models.IntegerField()
    max_principals = models.IntegerField()
    audit_retention_days = models.IntegerField()
    min_sync_interval_seconds = models.IntegerField()
    price_cents_monthly = models.IntegerField(default=0)

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
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    peak_objects = models.IntegerField(default=0)
    peak_principals = models.IntegerField(default=0)
    total_audit_entries = models.IntegerField(default=0)
    finalized = models.BooleanField(default=False)

    class Meta:
        db_table = "billing_periods"
        indexes = [
            models.Index(fields=["account", "period_start"]),
        ]

    def __str__(self):
        return f"{self.account_id} {self.period_start.date()} - {self.period_end.date()}"
