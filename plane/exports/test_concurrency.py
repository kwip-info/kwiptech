from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest import skipUnless

from django.db import connection, connections, close_old_connections
from django.test import TransactionTestCase
from django.utils import timezone
from plane.access.auth import Principal
from plane.access.models import Identity, Workspace
from plane.catalog.services import register_dataset, register_source, ingest_batch
from plane.commerce.models import BillingAccount, Delivery
from .models import ExportJob, ExportChunk
from .services import create_export, process_page


@skipUnless(connection.vendor == 'postgresql', 'PostgreSQL export locking contract')
class ExportConcurrencyTests(TransactionTestCase):
    def setUp(self):
        workspace = Workspace.objects.create(owner=Identity.objects.create(subject='user_export_concurrent'))
        self.principal = Principal(workspace, 'session')
        BillingAccount.objects.create(workspace=workspace, status='active', period_start=timezone.now() - timedelta(days=1), period_end=timezone.now() + timedelta(days=1))
        self.dataset = register_dataset({'slug': 'concurrent', 'title': 'Concurrent', 'schema_version': 1, 'fields': {'name': {'type': 'string'}}})
        source = register_source(self.dataset, {'slug': 'example', 'name': 'Example', 'url': 'https://example.com', 'schema_version': 1, 'attribution': 'Synthetic', 'license_url': 'https://example.com/license', 'rights_status': 'approved'})
        self.dataset.status = 'published'
        self.dataset.save()
        ingest_batch(source, [{'external_id': 'one', 'payload': {'name': 'Example'}, 'observed_at': '2026-01-01T00:00:00Z'}], 'seed')

    def concurrent(self, function):
        barrier = Barrier(2)
        def run():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return function()
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [pool.submit(run) for _ in range(2)]
            return [r.result(timeout=20) for r in results]

    def test_duplicate_create_has_one_job(self):
        jobs = self.concurrent(lambda: create_export(self.principal, self.dataset.slug, max_credits=100, request_id='stable'))
        self.assertEqual(jobs[0].pk, jobs[1].pk)
        self.assertEqual(ExportJob.objects.count(), 1)

    def test_concurrent_workers_bill_and_write_once(self):
        job = create_export(self.principal, self.dataset.slug, max_credits=100, request_id='stable')
        self.concurrent(lambda: process_page(job.pk))
        self.assertEqual(Delivery.objects.count(), 1)
        self.assertEqual(ExportChunk.objects.count(), 1)
        job.refresh_from_db()
        self.assertEqual(job.rows, 1)
        self.assertEqual(job.credits, 1)
