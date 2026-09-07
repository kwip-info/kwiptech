import json
import sys

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from plane.catalog.services import register_dataset, register_source


class Command(BaseCommand):
    help = 'Register a dataset and optional sources from an operator JSON manifest.'

    def add_arguments(self, parser):
        parser.add_argument('manifest', help='JSON file path or - for stdin')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        try:
            raw = sys.stdin.read(2_000_001) if options['manifest'] == '-' else self.read_file(options['manifest'])
            manifest = json.loads(raw)
            sources = manifest.pop('sources', [])
            with transaction.atomic():
                dataset = register_dataset(manifest)
                for source in sources:
                    register_source(dataset, source)
                if options['dry_run']:
                    transaction.set_rollback(True)
                self.stdout.write(json.dumps({'slug': dataset.slug, 'sources': len(sources), 'dry_run': options['dry_run']}))
        except (ValueError, OSError, ValidationError, TypeError, AttributeError) as exc:
            raise CommandError(str(exc)) from exc

    def read_file(self, path):
        with open(path) as handle:
            return handle.read(2_000_001)
