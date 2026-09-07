from django.contrib import admin
from .models import Dataset, SchemaVersion, Source, IngestionBatch, Record, RecordVersion


@admin.register(Dataset)
class DatasetAdmin(admin.ModelAdmin):
    list_display = ('slug', 'title', 'status', 'credits_per_record')
    list_filter = ('status', 'category')


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ('slug', 'dataset', 'rights_status', 'active')
    list_filter = ('rights_status', 'active')


@admin.register(SchemaVersion, IngestionBatch, Record, RecordVersion)
class ImmutableAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
