from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class Dataset(models.Model):
    slug = models.SlugField(unique=True)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=12, choices=[(v, v) for v in ('draft', 'published', 'withdrawn')], default='draft')
    credits_per_record = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(credits_per_record__gte=1), name='catalog_positive_price')]

    def clean(self):
        if self.status == 'published' and (not self.pk or not self.sources.filter(active=True, rights_status='approved').exists()):
            raise ValidationError('Publication requires an active source with approved redistribution rights.')

    def __str__(self):
        return self.title


class SchemaVersion(models.Model):
    dataset = models.ForeignKey(Dataset, on_delete=models.PROTECT, related_name='schemas')
    version = models.PositiveIntegerField()
    fields = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['dataset', 'version'], name='catalog_unique_schema'), models.CheckConstraint(condition=Q(version__gte=1), name='catalog_positive_schema')]

    def clean(self):
        from .services import validate_schema
        validate_schema(self.fields)
        if self.dataset_id:
            for previous in type(self).objects.filter(dataset_id=self.dataset_id).exclude(pk=self.pk):
                older, newer = (previous.fields, self.fields) if previous.version < self.version else (self.fields, previous.fields)
                for name, spec in older.items():
                    if name not in newer or newer[name]['type'] != spec['type']:
                        raise ValidationError('Schema evolution must preserve existing fields and types.')
                    if spec['type'] == 'enum' and not set(spec['values']) <= set(newer[name]['values']):
                        raise ValidationError('Schema evolution must preserve existing enum values.')
        if self.pk:
            old = type(self).objects.get(pk=self.pk)
            if (old.fields, old.dataset_id, old.version) != (self.fields, self.dataset_id, self.version):
                raise ValidationError('Schema versions are immutable; register a new version.')

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class Source(models.Model):
    dataset = models.ForeignKey(Dataset, on_delete=models.PROTECT, related_name='sources')
    slug = models.SlugField()
    name = models.CharField(max_length=200)
    url = models.URLField(max_length=2000)
    attribution = models.TextField(blank=True)
    license_url = models.URLField(max_length=2000, blank=True)
    rights_status = models.CharField(max_length=12, choices=[(v, v) for v in ('pending', 'evaluation', 'approved', 'blocked')], default='pending')
    active = models.BooleanField(default=True)
    schema = models.ForeignKey(SchemaVersion, on_delete=models.PROTECT, related_name='sources')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['dataset', 'slug'], name='catalog_unique_source')]

    def clean(self):
        if self.pk:
            old = type(self).objects.get(pk=self.pk)
            if old.dataset_id != self.dataset_id or old.slug != self.slug:
                raise ValidationError('Source identity is immutable; register another source.')
        if self.schema_id and self.schema.dataset_id != self.dataset_id:
            raise ValidationError('Schema must belong to source dataset.')
        if self.rights_status in ('evaluation', 'approved') and not (self.attribution and self.license_url):
            raise ValidationError('Approved rights require attribution and a license/evidence URL.')
        if self.rights_status == 'evaluation' and self.dataset.status != 'draft':
            raise ValidationError('Evaluation sources require a draft dataset.')


class CollectionState(models.Model):
    source = models.OneToOneField(Source, on_delete=models.PROTECT, related_name='collection_state')
    next_allowed_at = models.DateTimeField(null=True, blank=True)
    last_success_batch = models.ForeignKey('IngestionBatch', null=True, blank=True, on_delete=models.SET_NULL)


class CollectionRun(models.Model):
    source = models.ForeignKey(Source, on_delete=models.PROTECT, related_name='collection_runs')
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, default='running')
    manifest_hash = models.CharField(max_length=64)
    summary = models.JSONField(default=dict)


class IngestionBatch(models.Model):
    source = models.ForeignKey(Source, on_delete=models.PROTECT, related_name='batches')
    idempotency_key = models.CharField(max_length=200)
    request_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=12, default='complete')
    result = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['source', 'idempotency_key'], name='catalog_unique_batch')]


class Record(models.Model):
    dataset = models.ForeignKey(Dataset, on_delete=models.PROTECT, related_name='records')
    source = models.ForeignKey(Source, on_delete=models.PROTECT, related_name='records')
    external_id = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['source', 'external_id'], name='catalog_unique_record')]


class RecordVersion(models.Model):
    record = models.ForeignKey(Record, on_delete=models.PROTECT, related_name='versions')
    schema = models.ForeignKey(SchemaVersion, on_delete=models.PROTECT)
    batch = models.ForeignKey(IngestionBatch, on_delete=models.PROTECT, related_name='versions')
    payload = models.JSONField()
    observed_at = models.DateTimeField()
    effective_at = models.DateTimeField(null=True, blank=True)
    source_url = models.URLField(max_length=2000)
    source_metadata = models.JSONField(default=dict)
    content_hash = models.CharField(max_length=64)
    tombstone = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['record', '-id'], name='catalog_record_revision')]
