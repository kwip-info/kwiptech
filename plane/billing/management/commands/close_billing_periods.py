"""Management command to close expired billing periods.

Run daily via cron or Heroku Scheduler:
    python manage.py close_billing_periods
"""

from django.core.management.base import BaseCommand

from plane.billing.tasks import close_expired_periods


class Command(BaseCommand):
    help = "Close expired billing periods, report metered usage to Stripe, create next periods."

    def handle(self, *args, **options):
        closed = close_expired_periods()
        self.stdout.write(self.style.SUCCESS(f"Closed {closed} billing period(s)."))
