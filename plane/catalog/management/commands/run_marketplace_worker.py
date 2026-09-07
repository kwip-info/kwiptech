"""One conservative worker for bounded marketplace background responsibilities."""
import io
import time
from datetime import timedelta

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from django.db.models import Q
from django.utils import timezone

from plane.access.models import DeviceGrant, RateBucket
from plane.commerce.models import MeterOutbox
from plane.commerce.stripe_gateway import dispatch_one
from plane.exports.models import ExportJob
from plane.exports.services import process_page


# Cadences are minimum gaps after completion, not a catch-up queue after downtime.
INTERVALS = {'exports': 10, 'dispatch': 30, 'reconcile': 300, 'cleanup': 300}


def provider_configured():
    # Pausing billing also pauses provider traffic. Pending financial records stay
    # durable for explicit operator recovery; this never silently discards them.
    return bool(getattr(settings, 'MARKET_BILLING_ENABLED', False)
                and getattr(settings, 'MARKET_STRIPE_SECRET_KEY', '')
                and getattr(settings, 'MARKET_STRIPE_PRO_PRICE_ID', '')
                and getattr(settings, 'MARKET_STRIPE_OVERAGE_PRICE_ID', ''))


def cleanup_access(limit):
    now = timezone.now()
    grants = list(DeviceGrant.objects.filter(expires_at__lt=now).order_by('expires_at').values_list('pk', flat=True)[:limit])
    # Day-old rate windows are far outside the supported minute-based limits.
    buckets = list(RateBucket.objects.filter(starts_at__lt=now - timedelta(days=1)).order_by('starts_at').values_list('pk', flat=True)[:limit])
    DeviceGrant.objects.filter(pk__in=grants, expires_at__lt=now).delete()
    RateBucket.objects.filter(pk__in=buckets, starts_at__lt=now - timedelta(days=1)).delete()
    return {'expired_device_grants': len(grants), 'stale_rate_buckets': len(buckets)}


def execute_task(name, limit):
    output = io.StringIO()
    if name == 'exports':
        ids = list(ExportJob.objects.filter(status__in=['queued', 'running']).order_by('updated_at').values_list('pk', flat=True)[:limit])
        failed = 0
        for job_id in ids:
            try:
                process_page(job_id)
            except Exception:
                # One corrupt/transiently failing job must not starve its peers.
                failed += 1
        if failed:
            raise CommandError(f'{failed} export pages failed; other selected jobs continued.')
        return f'Processed {len(ids)} export pages.'
    elif name == 'dispatch':
        if not provider_configured():
            return 'skipped: billing disabled or provider configuration incomplete'
        now = timezone.now()
        rows = MeterOutbox.objects.exclude(status__in=['submitted', 'review']).filter(
            Q(lease_until__isnull=True) | Q(lease_until__lte=now),
            Q(next_attempt_at__isnull=True) | Q(next_attempt_at__lte=now),
        ).order_by('delivery__created_at').values_list('pk', flat=True)[:limit]
        counts = {}
        for pk in rows:
            result = dispatch_one(pk)
            counts[result] = counts.get(result, 0) + 1
        return str(counts)
    elif name == 'reconcile':
        if not provider_configured():
            return 'skipped: billing disabled or provider configuration incomplete'
        call_command('reconcile_billing', limit=limit, stdout=output)
    elif name == 'cleanup':
        from plane.catalog.connectors.jobs import purge_expired
        output.write(f'Expired evaluation versions removed: {purge_expired()}. ')
        call_command('cleanup_exports', limit=limit, stdout=output)
        call_command('purge_delivery_cache', limit=limit, stdout=output)
        output.write(str(cleanup_access(limit)))
    else:
        raise ValueError('Unknown worker task')
    return output.getvalue().strip()


class Command(BaseCommand):
    help = 'Run bounded export, billing and expiry maintenance with conservative polling.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Run each task once, then exit (nonzero on any task failure).')
        parser.add_argument('--limit', type=int, default=25, help='Maximum items/pages per task batch (1–100).')

    def handle(self, *args, **options):
        limit = options['limit']
        if not 1 <= limit <= 100:
            raise CommandError('limit must be 1–100')
        due = dict.fromkeys(INTERVALS, 0.0)
        while True:
            failures = []
            for name, interval in INTERVALS.items():
                if not options['once'] and time.monotonic() < due[name]:
                    continue
                close_old_connections()
                try:
                    result = execute_task(name, limit)
                    self.stdout.write(f'{name}: {result}')
                except Exception as exc:
                    # Log only the type: provider exceptions can contain request
                    # details. Durable state and provider dashboard aid diagnosis.
                    self.stderr.write(f'{name}: failed ({type(exc).__name__}); retry on next interval')
                    failures.append(name)
                finally:
                    close_old_connections()
                    due[name] = time.monotonic() + interval
            if options['once']:
                if failures:
                    raise CommandError('Worker tasks failed: ' + ', '.join(failures))
                return
            time.sleep(5)
