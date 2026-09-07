"""Bounded DB-backed exports. A page, usage receipt and output commit together."""
import csv
import io
import json
from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction, connection
from django.utils import timezone

from plane.access.auth import Principal, refresh_principal
from plane.access.errors import Problem
from plane.access.models import Workspace
from plane.catalog.models import Dataset
from plane.catalog.services import digest, read_records
from plane.commerce.services import account_for, deliver, pro_active
from .models import ExportChunk, ExportJob, ExportRequest


def option(name, default):
    return getattr(settings, 'MARKET_EXPORT_' + name, default)


def authorize(principal, dataset):
    principal = refresh_principal(principal, lock=connection.in_atomic_block)
    workspace = principal.workspace
    principal.require('exports:read', dataset=dataset.slug)
    principal.require('datasets:read', dataset=dataset.slug)
    if not pro_active(account_for(workspace)):
        raise Problem('pro_required', 'Exports require an active Pro plan.', 403)
    return principal


def job_authority(job):
    principal = Principal(job.workspace, job.actor_kind, job.actor_key)
    principal = authorize(principal, job.dataset)
    authorize_sources(principal, job)
    return principal



def authorize_sources(principal, job):
    if principal.key and principal.key.source_slugs:
        sources = set(job.dataset.sources.filter(pk__in=job.source_ids).values_list('slug', flat=True))
        if sources - set(principal.key.source_slugs):
            raise Problem('source_forbidden', 'This key cannot access every source in this export.', 403)

def available(job):
    if job.expires_at <= timezone.now():
        raise Problem('export_expired', 'Export expired; create a new export.', 410)
    job.dataset.refresh_from_db()
    if job.dataset.status != 'published' or job.dataset.sources.filter(pk__in=job.source_ids, active=True, rights_status='approved').count() != len(job.source_ids):
        raise Problem('export_source_withdrawn', 'A dataset or source was withdrawn; this export is unavailable.', 403)
    job_authority(job)


@transaction.atomic
def create_export(principal, dataset_slug, *, filters=None, format='jsonl', max_credits=None, request_id=None):
    if not isinstance(dataset_slug, str) or not 1 <= len(dataset_slug) <= 50:
        raise Problem('invalid_dataset', 'Provide a dataset slug.')
    if not isinstance(format, str) or format not in ('jsonl', 'csv'):
        raise Problem('invalid_format', 'Choose jsonl or csv.')
    if type(max_credits) is not int or not 1 <= max_credits <= option('MAX_CREDITS', 1_000_000):
        raise Problem('invalid_budget', 'Provide a positive max_credits within the export ceiling.')
    if not isinstance(request_id, str) or not 1 <= len(request_id) <= 200:
        raise Problem('idempotency_required', 'Provide an Idempotency-Key of 1–200 characters.')
    fingerprint = digest({'dataset': dataset_slug, 'filters': filters or {}, 'format': format, 'max_credits': max_credits, 'actor_kind': principal.kind, 'actor_key': str(principal.key.pk) if principal.key else None})
    Workspace.objects.select_for_update().get(pk=principal.workspace.pk)
    previous = ExportRequest.objects.select_related('job__dataset').filter(workspace=principal.workspace, request_id=request_id).first()
    if previous:
        if previous.fingerprint != fingerprint:
            raise Problem('idempotency_conflict', 'That export request ID was used for different input.', 409)
        if previous.job is None:
            raise Problem('export_expired', 'The original export expired. Use a new request ID for new work.', 410)
        return owned_job(principal, previous.job.pk)
    dataset = Dataset.objects.select_for_update().filter(slug=dataset_slug, status='published').first()
    if dataset is None:
        raise Problem('dataset_unavailable', 'Published dataset not found.', 404)
    principal = authorize(principal, dataset)
    preview = read_records(dataset, filters=filters, limit=1)
    if not preview['count']:
        raise Problem('export_empty', 'No matching records; no export or charge was created.', 409)
    if max_credits < dataset.credits_per_record:
        raise Problem('invalid_budget', 'Budget must cover at least one record.')
    if ExportJob.objects.filter(workspace=principal.workspace, expires_at__gt=timezone.now()).count() >= option('MAX_JOBS', 20):
        raise Problem('export_job_limit', 'Wait for existing exports to expire before creating more.', 429)
    filters = filters or {}
    schema = dataset.schemas.order_by('-version').first()
    cursor = signing.dumps({'fingerprint': digest({'dataset': dataset.pk, 'filters': filters, 'fields': None}), 'watermark': preview['snapshot'], 'last_id': 0, 'schema_id': schema.pk}, salt='catalog.snapshot.v1', compress=True)
    restrictions = {'scopes': principal.key.scopes, 'dataset_slugs': principal.key.dataset_slugs, 'source_slugs': principal.key.source_slugs} if principal.key else {}
    job = ExportJob.objects.create(workspace=principal.workspace, actor_kind=principal.kind, actor_key=principal.key, actor_restrictions=restrictions, dataset=dataset,
        source_ids=list(dataset.sources.filter(active=True, rights_status='approved').values_list('pk', flat=True)), filters=filters, format=format,
        fields=list(schema.fields), cursor=cursor, snapshot=preview['snapshot'], max_credits=max_credits, expires_at=timezone.now() + timedelta(hours=24))
    ExportRequest.objects.create(workspace=principal.workspace, request_id=request_id, fingerprint=fingerprint, job=job)
    return job


def serialize(records, job):
    if job.format == 'jsonl':
        return ''.join(json.dumps(row, ensure_ascii=False, allow_nan=False, separators=(',', ':')) + '\n' for row in records)
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    if job.pages == 0:
        writer.writerow(['record_id', 'external_id', 'revision', 'source', 'source_url', 'observed_at', *job.fields])
    def safe(value):
        if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
            return "'" + value
        if isinstance(value, str) and value.startswith(('\t', '\r', '\n')):
            return "'" + value
        return value
    for row in records:
        writer.writerow([safe(v) for v in [row['id'], row['external_id'], row['revision'], row['source']['slug'], row['source_url'], row['observed_at'], *(row['data'].get(field, '') for field in job.fields)]])
    return output.getvalue()


@transaction.atomic
def process_page(job_id):
    workspace_id = ExportJob.objects.values_list('workspace_id', flat=True).get(pk=job_id)
    Workspace.objects.select_for_update().get(pk=workspace_id)
    job = ExportJob.objects.select_for_update(of=('self',)).select_related('workspace__owner', 'actor_key', 'dataset').get(pk=job_id)
    if job.status not in ('queued', 'running'):
        return job
    try:
        Workspace.objects.select_for_update().get(pk=job.workspace_id)
        Dataset.objects.select_for_update().get(pk=job.dataset_id)
        list(job.dataset.sources.select_for_update().filter(pk__in=job.source_ids))
        available(job)
        principal = job_authority(job)
        row_limit = option('MAX_ROWS', 10_000) - job.rows
        remaining = job.max_credits - job.credits
        limit = min(100, row_limit, remaining // job.dataset.credits_per_record)
        if limit < 1:
            job.status, job.error_code = 'partial', 'export_cap_reached'
        else:
            # Nested savepoint rolls back both delivery accounting and output on
            # serialization/storage/budget failure. Retrying the page uses same ID.
            with transaction.atomic():
                content_holder = {}
                def producer():
                    response = read_records(job.dataset, filters=job.filters, limit=limit, cursor=job.cursor)
                    content = serialize(response['records'], job)
                    if job.byte_count + len(content.encode()) > option('MAX_BYTES', 10 * 1024 * 1024):
                        raise Problem('export_byte_cap', 'Export byte ceiling reached.', 409)
                    content_holder['content'] = content
                    return response
                response = deliver(principal, job.dataset, f'export:{job.pk}:{job.pages}', digest({'job': str(job.pk), 'page': job.pages, 'cursor': job.cursor}), producer, max_credits=remaining)
                content = content_holder.get('content')
                if content is None:
                    content = serialize(response['records'], job)
                ExportChunk.objects.create(job=job, page=job.pages, content=content, rows=response['count'])
                job.pages += 1
                job.rows += response['count']
                job.byte_count += len(content.encode())
                job.credits += response['usage']['credits']
                job.cursor = response['next_cursor'] or ''
                job.status = 'running' if job.cursor else 'complete'
    except (Problem, ValidationError) as exc:
        job.error_code = exc.code if isinstance(exc, Problem) else 'export_snapshot_invalid'
        # Rights/auth failures never make an existing artifact downloadable.
        if job.error_code in ('quota_exceeded', 'spend_cap_exceeded', 'request_budget_exceeded', 'export_byte_cap', 'response_too_large'):
            job.status = 'partial' if job.rows else 'failed'
        else:
            job.status = 'failed'
    job.save()
    return job


@transaction.atomic
def owned_job(principal, job_id):
    Workspace.objects.select_for_update().get(pk=principal.workspace.pk)
    job = ExportJob.objects.select_related('workspace__owner', 'actor_key', 'dataset').filter(pk=job_id, workspace=principal.workspace).first()
    if job is None:
        raise Problem('export_not_found', 'Export not found.', 404)
    Dataset.objects.select_for_update().get(pk=job.dataset_id)
    list(job.dataset.sources.select_for_update().filter(pk__in=job.source_ids))
    principal = authorize(principal, job.dataset)
    authorize_sources(principal, job)
    available(job)
    return job


@transaction.atomic
def download(principal, job_id):
    job = owned_job(principal, job_id)
    if job.status not in ('complete', 'partial') or not job.rows:
        raise Problem('export_not_ready', 'Export is not ready for download.', 409)
    return job, ''.join(job.chunks.order_by('page').values_list('content', flat=True))


def job_json(job):
    return {'id': str(job.pk), 'dataset': job.dataset.slug, 'status': job.status, 'format': job.format, 'rows': job.rows, 'credits': job.credits,
        'max_credits': job.max_credits, 'bytes': job.byte_count, 'snapshot': job.snapshot, 'expires_at': job.expires_at.isoformat(), 'error_code': job.error_code,
        'download_ready': job.status in ('complete', 'partial') and job.rows > 0, 'notice': 'Credits are charged as records are prepared. Downloads do not add charges. Partial exports are explicitly marked.'}
