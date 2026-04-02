"""Seed default billing plans.

Creates or updates the Free and Pro plan records. Safe to run
multiple times (idempotent via get_or_create + update).

Usage:
    python manage.py seed_plans
"""

from django.core.management.base import BaseCommand

from plane.billing.models import Plan


PLANS = [
    {
        "id": "free",
        "name": "Free",
        "max_objects": 1000,
        "max_principals": 50,
        "audit_retention_days": 7,
        "min_sync_interval_seconds": 3600,
        "price_cents_monthly": 0,
        "included_objects": 1000,
        "included_principals": 50,
        "overage_per_object_cents": 0,
        "overage_per_principal_cents": 0,
    },
    {
        "id": "pro",
        "name": "Pro",
        "max_objects": 100000,
        "max_principals": 500,
        "audit_retention_days": 90,
        "min_sync_interval_seconds": 60,
        "price_cents_monthly": 4900,
        "included_objects": 10000,
        "included_principals": 100,
        "overage_per_object_cents": 1,
        "overage_per_principal_cents": 5,
    },
    {
        "id": "enterprise",
        "name": "Enterprise",
        "max_objects": 10000000,
        "max_principals": 50000,
        "audit_retention_days": 365,
        "min_sync_interval_seconds": 10,
        "price_cents_monthly": 0,  # Custom pricing
        "included_objects": 100000,
        "included_principals": 1000,
        "overage_per_object_cents": 0,
        "overage_per_principal_cents": 0,
    },
]


class Command(BaseCommand):
    help = "Create or update default billing plans (Free, Pro, Enterprise)."

    def handle(self, *args, **options):
        for plan_data in PLANS:
            plan_id = plan_data.pop("id")
            plan, created = Plan.objects.update_or_create(
                id=plan_id,
                defaults=plan_data,
            )
            action = "Created" if created else "Updated"
            self.stdout.write(f"  {action} plan: {plan.name}")
            plan_data["id"] = plan_id  # Restore for reuse

        self.stdout.write(self.style.SUCCESS(f"Seeded {len(PLANS)} plans."))
