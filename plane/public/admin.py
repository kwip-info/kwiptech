from django.contrib import admin

from plane.public.models import DigestPilotLead


@admin.register(DigestPilotLead)
class DigestPilotLeadAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "company",
        "name",
        "email",
        "deployment_target",
        "timeline",
        "status",
    )
    list_filter = ("status", "deployment_target", "timeline", "created_at")
    search_fields = ("company", "name", "email", "document_types", "use_case")
    readonly_fields = ("created_at",)
    fieldsets = (
        (None, {"fields": ("status", "created_at")}),
        ("Contact", {"fields": ("name", "email", "company", "role")}),
        (
            "Pilot details",
            {"fields": ("document_types", "deployment_target", "timeline", "use_case")},
        ),
        ("Internal notes", {"fields": ("notes",)}),
    )
