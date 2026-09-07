from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from plane.exports.models import ExportJob


class Command(BaseCommand):
    help = 'Remove up to --limit expired export artifacts; billing receipts remain.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=100)

    def handle(self, *args, **options):
        if not 1 <= options['limit'] <= 1000:
            raise CommandError('limit must be 1–1000')
        ids = list(ExportJob.objects.filter(expires_at__lte=timezone.now()).order_by('expires_at').values_list('pk', flat=True)[:options['limit']])
        ExportJob.objects.filter(pk__in=ids).delete()
        self.stdout.write(f'Removed {len(ids)} expired exports.')
