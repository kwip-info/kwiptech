from datetime import timedelta
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from plane.commerce.models import Delivery


class Command(BaseCommand):
    help = 'Remove expired raw response payloads while permanently retaining accounting/idempotency receipts.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=1000)

    def handle(self, *args, **options):
        limit = options['limit']
        if not 1 <= limit <= 10000:
            raise CommandError('limit must be 1–10000')
        ids = list(Delivery.objects.filter(created_at__lt=timezone.now() - timedelta(hours=24)).exclude(response={}).order_by('created_at').values_list('pk', flat=True)[:limit])
        count = Delivery.objects.filter(pk__in=ids).update(response={})
        self.stdout.write(f'Purged {count} cached responses; receipts retained.')
