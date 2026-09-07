import time
from django.core.management.base import BaseCommand, CommandError
from plane.exports.models import ExportJob
from plane.exports.services import process_page


class Command(BaseCommand):
    help = 'Process bounded export pages; --once is suitable for repeatable scheduled runs.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true')
        parser.add_argument('--limit', type=int, default=100, help='Maximum pages per iteration (1–1000)')

    def handle(self, *args, **options):
        if not 1 <= options['limit'] <= 1000:
            raise CommandError('limit must be 1–1000')
        while True:
            processed = 0
            for _ in range(options['limit']):
                job_id = ExportJob.objects.filter(status__in=['queued', 'running']).order_by('updated_at').values_list('pk', flat=True).first()
                if job_id is None:
                    break
                process_page(job_id)
                processed += 1
            self.stdout.write(f'Processed {processed} export pages.')
            if options['once']:
                return
            time.sleep(2 if processed else 10)
