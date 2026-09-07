from django.db.models import Q
from django.utils import timezone
from django.core.management.base import BaseCommand, CommandError
from plane.commerce.models import MeterOutbox
from plane.commerce.stripe_gateway import dispatch_one


class Command(BaseCommand):
    help = 'Submit bounded durable overage events; ambiguous old events require review.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=100)

    def handle(self, *args, **options):
        limit = options['limit']
        if not 1 <= limit <= 1000:
            raise CommandError('limit must be 1–1000')
        now = timezone.now()
        due = MeterOutbox.objects.exclude(status__in=['submitted', 'review']).filter(
            Q(lease_until__isnull=True) | Q(lease_until__lte=now),
            Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now))
        ids = list(due.order_by('delivery__created_at').values_list('pk', flat=True)[:limit])
        results = {}
        for pk in ids:
            result = dispatch_one(pk)
            results[result] = results.get(result, 0) + 1
        self.stdout.write(str(results))
