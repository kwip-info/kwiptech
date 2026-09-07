"""Read-only release evidence, including the explicitly empty catalog launch gate."""
import json
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from plane.catalog.models import Dataset, Source, Record, RecordVersion, IngestionBatch
from plane.exports.models import ExportJob


class Command(BaseCommand):
    help = 'Report marketplace database readiness without reading record payloads or provider secrets.'

    def add_arguments(self, parser):
        parser.add_argument('--require-empty', action='store_true')
        parser.add_argument('--production', action='store_true')

    def handle(self, *args, **options):
        counts = {model._meta.label_lower: model.objects.count()
                  for model in (Dataset, Source, Record, RecordVersion, IngestionBatch, ExportJob)}
        problems = []
        if options['require_empty'] and any(counts.values()):
            problems.append('Marketplace catalog, records, batches and exports must be empty for this launch.')
        if options['production']:
            if connection.vendor != 'postgresql':
                problems.append('Production requires PostgreSQL.')
            if settings.DEBUG or settings.ROOT_URLCONF != 'plane.urls':
                problems.append('Production must disable DEBUG and use the production URL configuration.')
            if len(settings.SECRET_KEY) < 50 or settings.SECRET_KEY.startswith('insecure'):
                problems.append('Production requires a strong application secret.')
            if not settings.MARKET_ORIGIN.startswith('https://') or not settings.MARKET_CLERK_ISSUER.startswith('https://'):
                problems.append('Production marketplace and Clerk issuer must use HTTPS.')
            if not settings.MARKET_CLERK_PUBLISHABLE_KEY or not settings.MARKET_CLERK_WEBHOOK_SECRET:
                problems.append('Clerk sign-in and signed lifecycle webhook configuration are required.')
        self.stdout.write(json.dumps({'database': connection.vendor, 'counts': counts, 'ok': not problems,
                                     'billing_enabled': settings.MARKET_BILLING_ENABLED, 'problems': problems}))
        if problems:
            raise CommandError('Marketplace preflight failed; see the non-sensitive report above.')
