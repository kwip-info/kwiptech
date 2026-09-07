import json
import os
from django.core.management.base import BaseCommand, CommandError
from plane.catalog.connectors.jobs import CollectionError, collect, manifest, policy, purge_expired


class Command(BaseCommand):
    help = 'Inspect the source manifest, or explicitly fetch one bounded hosted evaluation sample.'

    def add_arguments(self, parser):
        parser.add_argument('--collect', action='store_true')
        parser.add_argument('--source', default='himalayas')

    def handle(self, *args, **options):
        try:
            policy(options['source'])
            if not options['collect']:
                self.stdout.write(json.dumps({'mode': 'plan', 'network_requests': 0, 'manifest': manifest()}))
                return
            if not os.environ.get('DYNO'):
                raise CommandError('Real-data collection runs on Heroku only. Local tests use synthetic transport fixtures.')
            purge_expired()
            self.stdout.write(json.dumps(collect(options['source'])))
        except CollectionError as exc:
            raise CommandError(exc.code) from None
