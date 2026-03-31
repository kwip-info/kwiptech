"""Admin registrations for core models."""

from django.contrib import admin

from plane.core.models import Account, ApiKey, SyncBatchRecord, SyncedAuditEntry


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ("id", "email", "plan", "status", "created_at")
    search_fields = ("email",)
    list_filter = ("plan", "status")


@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin):
    list_display = ("key_prefix", "account", "environment", "is_active", "created_at", "last_used_at")
    list_filter = ("environment", "is_active")
    search_fields = ("key_prefix", "account__email")


@admin.register(SyncedAuditEntry)
class SyncedAuditEntryAdmin(admin.ModelAdmin):
    list_display = ("sequence", "account", "action", "target_type", "target_id", "timestamp")
    list_filter = ("action", "target_type")
    search_fields = ("actor_id", "target_id")
    ordering = ("-sequence",)


@admin.register(SyncBatchRecord)
class SyncBatchRecordAdmin(admin.ModelAdmin):
    list_display = ("id", "account", "first_sequence", "last_sequence", "entry_count", "received_at")
    ordering = ("-received_at",)
