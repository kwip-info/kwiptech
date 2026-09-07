import stripe
from django.db.models import Q
from django.core.management.base import BaseCommand, CommandError
from plane.access.errors import Problem
from plane.commerce.models import BillingAccount, StripeEvent
from plane.commerce.stripe_gateway import process_event, reconcile_subscription, reconcile_meter, reconcile_deleted_account


class Command(BaseCommand):
    help = 'Process durable webhook events and refresh bounded current subscriptions.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=100)

    def handle(self, *args, **options):
        limit = options['limit']
        if not 1 <= limit <= 1000:
            raise CommandError('limit must be 1–1000')
        failed = 0
        for event_id in StripeEvent.objects.exclude(status='processed').order_by('received_at').values_list('pk', flat=True)[:limit]:
            try:
                process_event(event_id)
            except (Problem, stripe.StripeError, ValueError):
                failed += 1
        accounts = BillingAccount.objects.filter(Q(cancellation_requested_at__isnull=False, cancellation_completed_at__isnull=True) | ~Q(stripe_subscription_id='')).exclude(workspace__owner__deleted_at__isnull=False, cancellation_completed_at__isnull=False).select_related('workspace__owner').order_by('reconciled_at')
        for account in accounts[:limit]:
            try:
                if account.workspace.owner.deleted_at:
                    reconcile_deleted_account(account.pk)
                    continue
                reconcile_subscription(account.pk)
                summary = reconcile_meter(account.pk)
                if summary and summary.status != 'matched':
                    failed += 1
            except (Problem, stripe.StripeError, ValueError):
                failed += 1
        self.stdout.write(f'Billing reconciliation completed; failures={failed}.')
        if failed:
            raise CommandError('Some billing records need retry or review.')
