from django.contrib import admin
from .models import Identity, Workspace, ServiceKey

@admin.register(Identity)
class IdentityAdmin(admin.ModelAdmin):
    list_display = ('subject', 'active', 'is_operator', 'created_at')
    search_fields = ('subject',)

@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'owner')
    readonly_fields = ('id', 'created_at')

@admin.register(ServiceKey)
class ServiceKeyAdmin(admin.ModelAdmin):
    list_display = ('name', 'workspace', 'prefix', 'expires_at', 'revoked_at')
    exclude = ('token_hash',)
    readonly_fields = ('workspace', 'name', 'prefix', 'scopes', 'dataset_slugs', 'source_slugs', 'expires_at', 'created_at')
    def has_add_permission(self, request):
        return False
