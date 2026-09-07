import uuid
from django.db import models


class ExportJob(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey('access.Workspace', on_delete=models.PROTECT)
    actor_kind = models.CharField(max_length=10)
    actor_key = models.ForeignKey('access.ServiceKey', null=True, on_delete=models.SET_NULL)
    actor_restrictions = models.JSONField(default=dict)
    dataset = models.ForeignKey('catalog.Dataset', on_delete=models.PROTECT)
    source_ids = models.JSONField(default=list)
    filters = models.JSONField(default=dict)
    format = models.CharField(max_length=5, choices=[('jsonl', 'JSONL'), ('csv', 'CSV')])
    fields = models.JSONField(default=list)
    cursor = models.TextField()
    snapshot = models.PositiveBigIntegerField()
    status = models.CharField(max_length=12, default='queued')
    error_code = models.CharField(max_length=80, blank=True)
    max_credits = models.PositiveBigIntegerField()
    credits = models.PositiveBigIntegerField(default=0)
    rows = models.PositiveIntegerField(default=0)
    byte_count = models.PositiveIntegerField(default=0)
    pages = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)


class ExportChunk(models.Model):
    job = models.ForeignKey(ExportJob, on_delete=models.CASCADE, related_name='chunks')
    page = models.PositiveIntegerField()
    content = models.TextField()
    rows = models.PositiveIntegerField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['job', 'page'], name='exports_unique_page')]


class ExportRequest(models.Model):
    workspace = models.ForeignKey('access.Workspace', on_delete=models.PROTECT)
    request_id = models.CharField(max_length=200)
    fingerprint = models.CharField(max_length=64)
    job = models.OneToOneField(ExportJob, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['workspace', 'request_id'], name='exports_unique_request')]
