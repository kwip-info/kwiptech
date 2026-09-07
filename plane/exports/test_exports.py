from datetime import timedelta
from unittest.mock import patch
import csv
import io
import json
import pytest
from django.core.management import call_command
from django.test import override_settings, RequestFactory
from django.utils import timezone

from plane.access.auth import Principal, issue_key
from plane.access.errors import Problem
from plane.access.models import Identity, Workspace
from plane.catalog.services import register_dataset, register_source, ingest_batch
from plane.commerce.models import BillingAccount, Delivery
from .models import ExportJob, ExportChunk
from .services import create_export as create_export_service, process_page, download, owned_job

pytestmark = pytest.mark.django_db


def create_export(*args, **kwargs):
    import uuid
    kwargs.setdefault('request_id', str(uuid.uuid4()))
    return create_export_service(*args, **kwargs)


@pytest.fixture
def example():
    owner = Identity.objects.create(subject='user_exports')
    workspace = Workspace.objects.create(owner=owner)
    now = timezone.now()
    BillingAccount.objects.create(workspace=workspace, status='active', period_start=now - timedelta(days=1), period_end=now + timedelta(days=29))
    principal = Principal(workspace, 'session')
    dataset = register_dataset({'slug': 'synthetic-exports', 'title': 'Synthetic', 'schema_version': 1, 'fields': {'name': {'type': 'string'}}})
    source = register_source(dataset, {'slug': 'example', 'name': 'Example', 'url': 'https://example.com/data', 'schema_version': 1, 'rights_status': 'approved', 'attribution': 'Synthetic', 'license_url': 'https://example.com/license'})
    dataset.status = 'published'
    dataset.save()
    return principal, dataset, source


def seed(source, count=3, name='Example'):
    ingest_batch(source, [{'external_id': str(i), 'payload': {'name': name}, 'observed_at': '2026-01-01T00:00:00Z'} for i in range(count)], 'synthetic')


def test_free_and_empty_create_no_work(example):
    principal, dataset, source = example
    with pytest.raises(Problem, match='No matching'):
        create_export(principal, dataset.slug, max_credits=100)
    seed(source)
    BillingAccount.objects.filter(workspace=principal.workspace).update(status='free')
    with pytest.raises(Problem) as exc:
        create_export(principal, dataset.slug, max_credits=100)
    assert exc.value.status == 403
    assert not ExportJob.objects.exists()
    assert not Delivery.objects.exists()


def test_success_retry_and_free_redownload(example):
    principal, dataset, source = example
    seed(source)
    job = create_export(principal, dataset.slug, max_credits=100)
    assert not Delivery.objects.exists()
    job = process_page(job.pk)
    assert job.status == 'complete'
    assert job.rows == job.credits == 3
    assert process_page(job.pk).rows == 3
    _, content = download(principal, job.pk)
    assert len(content.splitlines()) == 3
    assert json.loads(content.splitlines()[0])['data'] == {'name': 'Example'}
    download(principal, job.pk)
    assert Delivery.objects.count() == 1
    assert ExportChunk.objects.count() == 1


def test_transaction_failure_retries_without_charges(example):
    principal, dataset, source = example
    seed(source)
    job = create_export(principal, dataset.slug, max_credits=100)
    with patch('plane.exports.services.ExportChunk.objects.create', side_effect=RuntimeError('storage failure')):
        with pytest.raises(RuntimeError):
            process_page(job.pk)
    assert not Delivery.objects.exists()
    assert not ExportChunk.objects.exists()
    assert process_page(job.pk).status == 'complete'
    assert Delivery.objects.count() == 1


def test_partial_budget_and_rows(example):
    principal, dataset, source = example
    seed(source, 5)
    job = create_export(principal, dataset.slug, max_credits=2)
    assert process_page(job.pk).rows == 2
    job = process_page(job.pk)
    assert job.status == 'partial'
    assert job.credits == 2
    assert len(download(principal, job.pk)[1].splitlines()) == 2
    with override_settings(MARKET_EXPORT_MAX_ROWS=1):
        second = create_export(principal, dataset.slug, max_credits=100)
        process_page(second.pk)
        assert process_page(second.pk).status == 'partial'


def test_byte_cap_no_charge(example):
    principal, dataset, source = example
    seed(source)
    job = create_export(principal, dataset.slug, max_credits=100)
    with override_settings(MARKET_EXPORT_MAX_BYTES=1):
        job = process_page(job.pk)
    assert job.status == 'failed'
    assert job.error_code == 'export_byte_cap'
    assert not Delivery.objects.exists()


def test_revoked_creator_key_blocks_worker_and_owner_download(example):
    principal, dataset, source = example
    seed(source)
    key, _ = issue_key(principal.workspace, 'Exporter', ['datasets:read', 'exports:read'])
    service = Principal(principal.workspace, 'service', key)
    job = create_export(service, dataset.slug, max_credits=100)
    process_page(job.pk)
    key.revoked_at = timezone.now()
    key.save()
    with pytest.raises(Problem):
        download(principal, job.pk)
    key.revoked_at = None
    key.save()
    second = create_export(service, dataset.slug, max_credits=100)
    key.revoked_at = timezone.now()
    key.save()
    assert process_page(second.pk).status == 'failed'
    assert Delivery.objects.count() == 1


def test_cross_account_and_dataset_scopes(example):
    principal, dataset, source = example
    seed(source)
    job = create_export(principal, dataset.slug, max_credits=100)
    other = Principal(Workspace.objects.create(owner=Identity.objects.create(subject='user_other')), 'session')
    with pytest.raises(Problem) as exc:
        owned_job(other, job.pk)
    assert exc.value.status == 404
    key, _ = issue_key(principal.workspace, 'Restricted', ['datasets:read', 'exports:read'], dataset_slugs=['other'])
    with pytest.raises(Problem):
        create_export(Principal(principal.workspace, 'service', key), dataset.slug, max_credits=100)


def test_source_withdrawal_and_dataset_withdrawal(example):
    principal, dataset, source = example
    seed(source)
    job = create_export(principal, dataset.slug, max_credits=100)
    process_page(job.pk)
    source.rights_status = 'blocked'
    source.save()
    with pytest.raises(Problem):
        download(principal, job.pk)
    source.rights_status = 'approved'
    source.save()
    dataset.status = 'withdrawn'
    dataset.save()
    with pytest.raises(Problem):
        download(principal, job.pk)


def test_csv_formula_escaped(example):
    principal, dataset, source = example
    seed(source, name=' =HYPERLINK("https://example.com")')
    job = create_export(principal, dataset.slug, format='csv', max_credits=100)
    process_page(job.pk)
    rows = list(csv.reader(io.StringIO(download(principal, job.pk)[1])))
    assert rows[1][-1].startswith("' =")
    assert len(rows) == 4


def test_snapshot_preserved_from_creation(example):
    principal, dataset, source = example
    seed(source)
    job = create_export(principal, dataset.slug, max_credits=100)
    ingest_batch(source, [{'external_id': '0', 'payload': {'name': 'Changed'}, 'observed_at': '2026-01-02T00:00:00Z'}], 'changed')
    process_page(job.pk)
    record = json.loads(download(principal, job.pk)[1].splitlines()[0])
    assert record['data']['name'] == 'Example'


def test_cleanup_expired_bounded_receipts_remain(example):
    principal, dataset, source = example
    seed(source)
    jobs = [create_export(principal, dataset.slug, max_credits=100) for _ in range(2)]
    for job in jobs:
        process_page(job.pk)
    ExportJob.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    with pytest.raises(Problem) as exc:
        download(principal, jobs[0].pk)
    assert exc.value.status == 410
    call_command('cleanup_exports', limit=1, stdout=io.StringIO())
    assert ExportJob.objects.count() == 1
    assert ExportChunk.objects.count() == 1
    assert Delivery.objects.count() == 2


@pytest.mark.parametrize('budget', [None, True, -1, '100', 10**100])
def test_budget_required(example, budget):
    with pytest.raises(Problem):
        create_export(example[0], example[1].slug, max_credits=budget)


def test_download_headers_and_command(example):
    from .views import artifact
    principal, dataset, source = example
    seed(source)
    job = create_export(principal, dataset.slug, max_credits=100)
    call_command('process_exports', once=True, limit=10, stdout=io.StringIO())
    with patch('plane.access.http.authenticate', return_value=principal):
        response = artifact(RequestFactory().get('/exports'), job.pk)
    assert response.status_code == 200
    assert response['Cache-Control'] == 'no-store'
    assert response['Content-Disposition'].startswith('attachment;')


def test_create_retry_conflict_and_expired_receipt(example):
    principal, dataset, source = example
    seed(source)
    job = create_export(principal, dataset.slug, max_credits=100, request_id='stable')
    assert create_export(principal, dataset.slug, max_credits=100, request_id='stable').pk == job.pk
    assert ExportJob.objects.count() == 1
    with pytest.raises(Problem) as exc:
        create_export(principal, dataset.slug, max_credits=101, request_id='stable')
    assert exc.value.status == 409
    ExportJob.objects.filter(pk=job.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    call_command('cleanup_exports', stdout=io.StringIO())
    with pytest.raises(Problem) as exc:
        create_export(principal, dataset.slug, max_credits=100, request_id='stable')
    assert exc.value.status == 410
    assert not ExportJob.objects.exists()


def test_explicit_creation_key_required(example):
    with pytest.raises(Problem) as exc:
        create_export_service(example[0], example[1].slug, max_credits=100)
    assert exc.value.code == 'idempotency_required'


def test_creator_key_deleted_fails_closed(example):
    principal, dataset, source = example
    seed(source)
    key, _ = issue_key(principal.workspace, 'Exporter', ['datasets:read', 'exports:read'])
    job = create_export(Principal(principal.workspace, 'service', key), dataset.slug, max_credits=100)
    key.delete()
    assert process_page(job.pk).status == 'failed'
    assert not Delivery.objects.exists()
