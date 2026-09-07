"""PostgreSQL locking contract; intentionally skipped on SQLite."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from unittest import skipUnless

from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, connections, transaction
from django.test import TransactionTestCase

from .models import Dataset, IngestionBatch, RecordVersion
from .services import ingest_batch, read_records, register_dataset, register_source


@skipUnless(connection.vendor == 'postgresql', 'PostgreSQL row-lock concurrency contract')
class CatalogConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.dataset = register_dataset({'slug': 'concurrent', 'title': 'Concurrent', 'schema_version': 1, 'fields': {'name': {'type': 'string'}}})
        self.source = register_source(self.dataset, {'slug': 'example', 'name': 'Example', 'url': 'https://example.com/data', 'schema_version': 1, 'rights_status': 'approved', 'attribution': 'Synthetic', 'license_url': 'https://example.com/license'})
        self.dataset.status = 'published'
        self.dataset.save()

    def item(self, identity='a', name='First'):
        return {'external_id': identity, 'payload': {'name': name}, 'observed_at': '2026-01-01T00:00:00Z'}

    def worker(self, fn):
        close_old_connections()
        try:
            return fn()
        finally:
            connections.close_all()

    def concurrent_batches(self, other):
        barrier = Barrier(2)

        def run(payload):
            barrier.wait(timeout=10)
            try:
                return ingest_batch(self.source, [payload], 'same-key')
            except ValidationError:
                return 'conflict'

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.worker, lambda p=p: run(p)) for p in (self.item(), other)]
            return [f.result(timeout=20) for f in futures]

    def test_same_key_same_input_commits_once(self):
        results = self.concurrent_batches(self.item())
        self.assertEqual(sorted(r['replayed'] for r in results), [False, True])
        self.assertEqual(IngestionBatch.objects.count(), 1)
        self.assertEqual(RecordVersion.objects.count(), 1)

    def test_same_key_conflicting_input_commits_once(self):
        results = self.concurrent_batches(self.item(name='Changed'))
        self.assertEqual(results.count('conflict'), 1)
        self.assertEqual(IngestionBatch.objects.count(), 1)
        self.assertEqual(RecordVersion.objects.count(), 1)

    def test_snapshot_waits_for_writer_then_stays_stable(self):
        ingest_batch(self.source, [self.item(), self.item('b')], 'initial')
        first = read_records(self.dataset, limit=1)
        locked = Event()
        release = Event()
        reading = Event()

        def writer():
            with transaction.atomic():
                Dataset.objects.select_for_update().get(pk=self.dataset.pk)
                ingest_batch(self.source, [self.item('b', 'Changed')], 'update')
                locked.set()
                if not release.wait(timeout=10):
                    raise AssertionError('Reader did not release writer')

        def reader():
            reading.set()
            return read_records(self.dataset, cursor=first['next_cursor'])

        with ThreadPoolExecutor(max_workers=2) as pool:
            write = pool.submit(self.worker, writer)
            self.assertTrue(locked.wait(timeout=10))
            read = pool.submit(self.worker, reader)
            self.assertTrue(reading.wait(timeout=10))
            release.set()
            write.result(timeout=20)
            result = read.result(timeout=20)
        self.assertEqual(result['snapshot'], first['snapshot'])
        self.assertEqual(result['records'][0]['data']['name'], 'First')
        self.assertEqual(read_records(self.dataset)['records'][1]['data']['name'], 'Changed')

    def test_new_snapshot_includes_writer_committing_ahead_of_it(self):
        locked = Event()
        reading = Event()
        release = Event()

        def writer():
            with transaction.atomic():
                Dataset.objects.select_for_update().get(pk=self.dataset.pk)
                ingest_batch(self.source, [self.item()], 'first')
                locked.set()
                if not release.wait(timeout=10):
                    raise AssertionError('Reader did not release writer')

        def reader():
            reading.set()
            return read_records(self.dataset)

        with ThreadPoolExecutor(max_workers=2) as pool:
            write = pool.submit(self.worker, writer)
            self.assertTrue(locked.wait(timeout=10))
            read = pool.submit(self.worker, reader)
            self.assertTrue(reading.wait(timeout=10))
            release.set()
            write.result(timeout=20)
            result = read.result(timeout=20)
        self.assertEqual(result['count'], 1)
        self.assertEqual(result['snapshot'], result['records'][0]['revision'])
