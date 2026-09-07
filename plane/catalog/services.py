"""Operator-only registration/ingestion and bounded, public catalog reads."""
import hashlib
import json
import math
import re
from datetime import date

from django.core import signing
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import transaction
from django.db.models import Max, OuterRef, Subquery
from django.utils.dateparse import parse_datetime
from django.utils.timezone import is_aware

from .models import Dataset, IngestionBatch, Record, RecordVersion, SchemaVersion, Source

MAX_BATCH = 500
MAX_BYTES = 2_000_000
TYPES = {'string', 'integer', 'number', 'boolean', 'datetime', 'date', 'enum'}


def digest(value):
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    except (TypeError, ValueError, RecursionError, OverflowError) as exc:
        raise ValidationError('Input must be finite JSON.') from exc
    if len(encoded) > MAX_BYTES:
        raise ValidationError('Request exceeds 2 MB.')
    return hashlib.sha256(encoded).hexdigest()


def validate_schema(fields):
    if not isinstance(fields, dict) or not 1 <= len(fields) <= 100:
        raise ValidationError('Schema requires 1–100 named fields.')
    for name, spec in fields.items():
        if not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,62}', name) or '__' in name:
            raise ValidationError('Invalid field name.')
        if not isinstance(spec, dict) or set(spec) - {'type', 'required', 'values', 'description'} or not isinstance(spec.get('type'), str) or spec['type'] not in TYPES:
            raise ValidationError(f'Invalid field specification: {name}.')
        if 'description' in spec and (not isinstance(spec['description'], str) or len(spec['description']) > 10_000):
            raise ValidationError('Field description must be a string of at most 10000 characters.')
        if 'required' in spec and type(spec['required']) is not bool:
            raise ValidationError('required must be boolean.')
        if spec['type'] == 'enum' and (not isinstance(spec.get('values'), list) or not 1 <= len(spec['values']) <= 100 or not all(isinstance(v, str) and len(v) <= 100_000 for v in spec['values'])):
            raise ValidationError('Enum requires 1–100 string values.')
    digest(fields)


def validate_manifest_strings(manifest, keys):
    for key in keys:
        if key in manifest and not isinstance(manifest[key], str):
            raise ValidationError(f'{key} must be a string.')
    slug = manifest.get('slug')
    if not isinstance(slug, str) or not re.fullmatch(r'[-a-zA-Z0-9_]{1,50}', slug):
        raise ValidationError('slug must be a valid 1–50 character identifier.')


def typed(value, spec):
    kind = spec['type']
    good = False
    if kind == 'string':
        good = isinstance(value, str) and len(value) <= 100_000
    elif kind == 'integer':
        good = type(value) is int and -(2**63) <= value < 2**63
    elif kind == 'number':
        good = type(value) in (int, float) and abs(value) <= 1e100 and math.isfinite(value)
    elif kind == 'boolean':
        good = type(value) is bool
    elif kind == 'enum':
        good = isinstance(value, str) and value in spec['values']
    elif kind == 'datetime':
        aware_datetime(value)
        good = True
    elif kind == 'date':
        try:
            good = isinstance(value, str) and date.fromisoformat(value).isoformat() == value
        except ValueError:
            pass
    if not good:
        raise ValidationError(f'Value does not match {kind}.')


def aware_datetime(value):
    try:
        parsed = parse_datetime(value) if isinstance(value, str) else None
    except ValueError:
        parsed = None
    if parsed is None or not is_aware(parsed):
        raise ValidationError('Timestamps must be ISO 8601 with a timezone.')
    return parsed


def validate_payload(payload, fields):
    if not isinstance(payload, dict) or set(payload) - set(fields):
        raise ValidationError('Payload has unknown fields or is not an object.')
    for name, spec in fields.items():
        if name not in payload:
            if spec.get('required', False):
                raise ValidationError(f'Missing required field: {name}.')
        else:
            typed(payload[name], spec)
    digest(payload)


@transaction.atomic
def register_dataset(manifest, dry_run=False):
    if not isinstance(manifest, dict) or set(manifest) - {'slug', 'title', 'description', 'category', 'status', 'credits_per_record', 'schema_version', 'fields'}:
        raise ValidationError('Unknown dataset manifest keys.')
    if not {'slug', 'title', 'schema_version', 'fields'} <= set(manifest):
        raise ValidationError('Dataset requires slug, title, schema_version and fields.')
    digest(manifest)
    validate_manifest_strings(manifest, ('slug', 'title', 'description', 'category', 'status'))
    validate_schema(manifest['fields'])
    if type(manifest['schema_version']) is not int or not 1 <= manifest['schema_version'] <= 2147483647:
        raise ValidationError('schema_version must be a positive integer.')
    if 'credits_per_record' in manifest and (type(manifest['credits_per_record']) is not int or not 1 <= manifest['credits_per_record'] <= 2147483647):
        raise ValidationError('credits_per_record must be a positive integer.')
    dataset = Dataset.objects.select_for_update().filter(slug=manifest['slug']).first() or Dataset(slug=manifest['slug'])
    for key in ('title', 'description', 'category', 'status', 'credits_per_record'):
        if key in manifest:
            setattr(dataset, key, manifest[key])
    dataset.full_clean()
    existing = SchemaVersion.objects.filter(dataset=dataset, version=manifest['schema_version']).first() if dataset.pk else None
    if existing and existing.fields != manifest['fields']:
        raise ValidationError('Existing schema version differs; use a new version.')
    schema = existing or SchemaVersion(dataset=dataset, version=manifest['schema_version'], fields=manifest['fields'])
    schema.full_clean(exclude=['dataset'] if not dataset.pk else [])
    if not dry_run:
        dataset.save()
        schema.dataset = dataset
        schema.save()
    return dataset


@transaction.atomic
def register_source(dataset, manifest, dry_run=False):
    allowed = {'slug', 'name', 'url', 'attribution', 'license_url', 'rights_status', 'active', 'schema_version'}
    if not isinstance(manifest, dict) or set(manifest) - allowed or not {'slug', 'name', 'url', 'schema_version'} <= set(manifest):
        raise ValidationError('Invalid source manifest.')
    digest(manifest)
    validate_manifest_strings(manifest, ('slug', 'name', 'url', 'attribution', 'license_url', 'rights_status'))
    if type(manifest['schema_version']) is not int or not 1 <= manifest['schema_version'] <= 2147483647:
        raise ValidationError('schema_version must be a positive integer.')
    if 'active' in manifest and type(manifest['active']) is not bool:
        raise ValidationError('active must be boolean.')
    Dataset.objects.select_for_update().get(pk=dataset.pk)
    try:
        schema = dataset.schemas.get(version=manifest['schema_version'])
    except SchemaVersion.DoesNotExist as exc:
        raise ValidationError('Unknown schema version.') from exc
    source = dataset.sources.select_for_update().filter(slug=manifest['slug']).first() or Source(dataset=dataset, slug=manifest['slug'])
    for key in allowed - {'schema_version'}:
        if key in manifest:
            setattr(source, key, manifest[key])
    source.schema = schema
    source.full_clean()
    if not dry_run:
        source.save()
    return source


@transaction.atomic
def ingest_batch(source, items, idempotency_key, dry_run=False):
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_BATCH:
        raise ValidationError('Batch requires 1–500 items.')
    if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 200:
        raise ValidationError('Idempotency key requires 1–200 characters.')
    request_hash = digest(items)
    # Dataset lock serializes writers across sources: committed version IDs form a
    # reliable snapshot watermark, including concurrent reads on PostgreSQL.
    dataset = Dataset.objects.select_for_update().get(pk=source.dataset_id)
    source = Source.objects.select_for_update().select_related('schema').get(pk=source.pk)
    evaluation = source.rights_status == 'evaluation' and dataset.status == 'draft'
    if not source.active or (source.rights_status != 'approved' and not evaluation):
        raise ValidationError('Source is inactive or redistribution rights are not approved.')
    previous = source.batches.filter(idempotency_key=idempotency_key).first()
    if previous:
        if previous.request_hash != request_hash:
            raise ValidationError('Idempotency key already used with different input.')
        return dict(previous.result, replayed=True)
    prepared = []
    seen = set()
    for item in items:
        if not isinstance(item, dict) or set(item) - {'external_id', 'payload', 'observed_at', 'effective_at', 'source_url', 'tombstone'}:
            raise ValidationError('Invalid item keys.')
        external_id = item.get('external_id')
        if not isinstance(external_id, str) or not 1 <= len(external_id) <= 500 or external_id in seen:
            raise ValidationError('Each item requires a unique external_id of 1–500 characters.')
        seen.add(external_id)
        tombstone = item.get('tombstone', False)
        if type(tombstone) is not bool:
            raise ValidationError('tombstone must be boolean.')
        payload = item.get('payload', {})
        if tombstone:
            if payload != {}:
                raise ValidationError('Tombstones must have an empty payload.')
        else:
            validate_payload(payload, source.schema.fields)
        observed = aware_datetime(item.get('observed_at'))
        effective = aware_datetime(item['effective_at']) if item.get('effective_at') is not None else None
        url = item.get('source_url', source.url)
        if not isinstance(url, str):
            raise ValidationError('source_url must be a URL string.')
        URLValidator(schemes=['http', 'https'])(url)
        if len(url) > 2000:
            raise ValidationError('Source URL exceeds 2000 characters.')
        prepared.append((external_id, payload, observed, effective, url, tombstone))
    if dry_run:
        return {'dry_run': True, 'validated': len(prepared), 'replayed': False}
    batch = IngestionBatch.objects.create(source=source, idempotency_key=idempotency_key, request_hash=request_hash)
    for external_id, payload, observed, effective, url, tombstone in prepared:
        record, _ = Record.objects.get_or_create(source=source, external_id=external_id, defaults={'dataset': source.dataset})
        RecordVersion.objects.create(record=record, schema=source.schema, batch=batch, payload=payload, observed_at=observed, effective_at=effective, source_url=url, tombstone=tombstone, source_metadata={'slug': source.slug, 'name': source.name, 'attribution': source.attribution, 'license_url': source.license_url}, content_hash=digest({'payload': payload, 'tombstone': tombstone}))
    batch.result = {'batch_id': batch.pk, 'versions_created': len(prepared), 'replayed': False}
    batch.save(update_fields=['result'])
    return batch.result


@transaction.atomic
def read_records(dataset, filters=None, limit=100, cursor=None, fields=None):
    dataset = Dataset.objects.select_for_update().get(pk=dataset.pk)
    if dataset.status != 'published':
        raise ValidationError('Dataset is not published.')
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValidationError('Limit must be 1–100.')
    if cursor is not None and (not isinstance(cursor, str) or len(cursor) > 8192):
        raise ValidationError('Cursor must be a string of at most 8192 characters.')
    filters = {} if filters is None else filters
    if not isinstance(filters, dict) or len(filters) > 10:
        raise ValidationError('Filters must be an object with at most 10 fields.')
    fingerprint = digest({'dataset': dataset.pk, 'filters': filters, 'fields': fields})
    watermark = RecordVersion.objects.filter(record__dataset=dataset).aggregate(value=Max('id'))['value'] or 0
    last_id = 0
    schema_id = None
    if cursor:
        try:
            state = signing.loads(cursor, salt='catalog.snapshot.v1', max_age=86400)
            if state['fingerprint'] != fingerprint:
                raise ValueError
            schema_id = state['schema_id']
            if type(schema_id) is not int:
                raise ValueError
            watermark, last_id = state['watermark'], state['last_id']
            if type(watermark) is not int or type(last_id) is not int or min(watermark, last_id) < 0:
                raise ValueError
        except (signing.BadSignature, KeyError, ValueError, TypeError) as exc:
            raise ValidationError('Invalid, expired, or mismatched cursor.') from exc
    schema = dataset.schemas.filter(pk=schema_id).first() if schema_id else dataset.schemas.order_by('-version').first()
    if schema is None:
        raise ValidationError('Dataset has no schema.')
    for name, value in filters.items():
        if name not in schema.fields:
            raise ValidationError('Unknown filter field.')
        typed(value, schema.fields[name])
    if fields is not None and (not isinstance(fields, list) or not fields or not all(isinstance(f, str) and f in schema.fields for f in fields) or len(set(fields)) != len(fields)):
        raise ValidationError('Projection must contain unique known field names.')
    latest = RecordVersion.objects.filter(record_id=OuterRef('record_id'), id__lte=watermark).order_by('-id').values('id')[:1]
    rows = RecordVersion.objects.filter(record__dataset=dataset, record__source__active=True, record__source__rights_status='approved', id__lte=watermark, record_id__gt=last_id, id=Subquery(latest), tombstone=False)
    for name, value in filters.items():
        rows = rows.filter(**{f'payload__{name}': value})
    page = list(rows.select_related('record__source', 'schema').order_by('record_id')[:limit + 1])
    results = []
    for row in page[:limit]:
        results.append({'id': row.record_id, 'external_id': row.record.external_id, 'revision': row.pk, 'schema_version': row.schema.version, 'source': row.source_metadata, 'source_url': row.source_url, 'observed_at': row.observed_at.isoformat(), 'effective_at': row.effective_at.isoformat() if row.effective_at else None, 'content_hash': row.content_hash, 'data': {k: v for k, v in row.payload.items() if fields is None or k in fields}})
    next_cursor = signing.dumps({'fingerprint': fingerprint, 'watermark': watermark, 'last_id': page[limit - 1].record_id, 'schema_id': schema.pk}, salt='catalog.snapshot.v1', compress=True) if len(page) > limit else None
    return {'records': results, 'count': len(results), 'next_cursor': next_cursor, 'snapshot': watermark}
