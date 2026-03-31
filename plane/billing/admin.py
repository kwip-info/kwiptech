"""Admin registrations for billing models."""

from django.contrib import admin

from plane.billing.models import BillingPeriod, Plan, UsageSnapshot


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "max_objects", "max_principals", "audit_retention_days")


@admin.register(UsageSnapshot)
class UsageSnapshotAdmin(admin.ModelAdmin):
    list_display = ("account", "active_objects", "active_principals", "recorded_at")
    ordering = ("-recorded_at",)


@admin.register(BillingPeriod)
class BillingPeriodAdmin(admin.ModelAdmin):
    list_display = ("account", "period_start", "period_end", "peak_objects", "peak_principals", "finalized")
    list_filter = ("finalized",)
