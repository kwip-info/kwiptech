import json
import sys

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from plane.catalog.models import Source
from plane.catalog.services import ingest_batch


class Command(BaseCommand):
    help = 'Validate or ingest an explicit JSON batch; never fetches source URLs.'

    def add_arguments(self, parser):
        parser.add_argument('dataset')
        parser.add_argument('source')
        parser.add_argument('manifest', help='JSON list file path or - for stdin')
        parser.add_argument('--idempotency-key', required=True)
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        try:
            source = Source.objects.get(dataset__slug=options['dataset'], slug=options['source'])
            if options['manifest'] == '-':
                raw = sys.stdin.read(2_000_001)
            else:
                with open(options['manifest']) as handle:
                    raw = handle.read(2_000_001)
            result = ingest_batch(source, json.loads(raw), options['idempotency_key'], dry_run=options['dry_run'])
            self.stdout.write(json.dumps(result))
        except (ValueError, OSError, ValidationError, Source.DoesNotExist) as exc:
            raise CommandError(str(exc)) from exc
