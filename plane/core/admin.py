"""Admin registrations for core models."""

from django.contrib import admin

from plane.core.models import (
    Account,
    ApiKey,
    AppMembership,
    Application,
    Membership,
    Organization,
    Permission,
    Role,
    SyncBatchRecord,
    SyncedAuditEntry,
)


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ("id", "email", "status", "created_at")
    search_fields = ("email",)
    list_filter = ("status",)


@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin):
    list_display = ("key_prefix", "account", "application", "environment", "is_active", "created_at")
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


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "owner", "plan", "is_personal", "status", "created_at")
    list_filter = ("plan", "status", "is_personal")
    search_fields = ("name", "slug")


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "organization", "is_default", "created_at")
    list_filter = ("is_default",)
    search_fields = ("name", "organization__name")


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "category")
    list_filter = ("category",)


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "is_default", "created_at")
    list_filter = ("is_default",)
    search_fields = ("name", "organization__name")


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("account", "organization", "role", "joined_at")
    search_fields = ("account__email", "organization__name")


@admin.register(AppMembership)
class AppMembershipAdmin(admin.ModelAdmin):
    list_display = ("membership", "application", "environment", "role", "created_at")
    list_filter = ("environment",)
    search_fields = ("membership__account__email", "application__name")
