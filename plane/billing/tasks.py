"""Billing period lifecycle — close periods, report metered usage to Stripe.

Run daily via management command or scheduler.
"""

import logging
from datetime import timedelta

from django.utils import timezone

from plane.billing.models import BillingPeriod, Plan
from plane.billing.stripe_client import get_stripe
from plane.core.models import Organization

logger = logging.getLogger(__name__)

PERIOD_DAYS = 30


def close_expired_periods():
    """Find and close all expired billing periods.

    For each expired period:
    1. Report metered overage to Stripe
    2. Mark as finalized
    3. Create the next period
    """
    now = timezone.now()
    expired = BillingPeriod.objects.filter(
        period_end__lt=now,
        finalized=False,
    ).select_related("organization")

    closed = 0
    for period in expired:
        try:
            _close_period(period)
            closed += 1
        except Exception:
            logger.exception("Failed to close billing period %s", period.id)

    logger.info("Closed %d billing periods", closed)
    return closed


def _close_period(period):
    """Close a single billing period and create the next one."""
    org = period.organization
    if org is None:
        period.finalized = True
        period.save(update_fields=["finalized"])
        return

    # Report metered usage to Stripe
    report_metered_usage(period, org)

    # Finalize
    period.finalized = True
    period.save(update_fields=["finalized"])

    # Create next period
    BillingPeriod.objects.create(
        account=period.account,
        organization=org,
        period_start=period.period_end,
        period_end=period.period_end + timedelta(days=PERIOD_DAYS),
    )
    logger.info("Closed period %s for org %s, created next", period.id, org.id)


def report_metered_usage(period, org):
    """Report overage to Stripe as metered usage records.

    Only reports for Pro orgs with active subscriptions and
    configured Stripe metered price IDs.
    """
    stripe = get_stripe()
    if stripe is None:
        return
    if not org.stripe_subscription_id:
        return

    plan = Plan.objects.filter(id=org.plan).first()
    if plan is None:
        return

    object_overage = max(0, period.peak_objects - plan.included_objects)
    principal_overage = max(0, period.peak_principals - plan.included_principals)

    if object_overage == 0 and principal_overage == 0:
        return

    # Find subscription items for metered prices
    try:
        subscription = stripe.Subscription.retrieve(
            org.stripe_subscription_id,
            expand=["items"],
        )
    except Exception:
        logger.warning("Failed to retrieve subscription for org %s", org.id, exc_info=True)
        return

    items_by_price = {
        item.price.id: item.id
        for item in subscription.items.data
    }

    if object_overage > 0 and plan.stripe_object_price_id:
        item_id = items_by_price.get(plan.stripe_object_price_id)
        if item_id:
            try:
                stripe.SubscriptionItem.create_usage_record(
                    item_id,
                    quantity=object_overage,
                    action="set",
                )
                logger.info("Reported %d object overage for org %s", object_overage, org.id)
            except Exception:
                logger.warning("Failed to report object usage for org %s", org.id, exc_info=True)

    if principal_overage > 0 and plan.stripe_principal_price_id:
        item_id = items_by_price.get(plan.stripe_principal_price_id)
        if item_id:
            try:
                stripe.SubscriptionItem.create_usage_record(
                    item_id,
                    quantity=principal_overage,
                    action="set",
                )
                logger.info("Reported %d principal overage for org %s", principal_overage, org.id)
            except Exception:
                logger.warning("Failed to report principal usage for org %s", org.id, exc_info=True)


def ensure_billing_period(org, account):
    """Get or create the active billing period for an org.

    Called from ingest_batch to ensure a period exists before
    updating peak usage.
    """
    now = timezone.now()
    period = (
        BillingPeriod.objects
        .filter(organization=org, finalized=False)
        .order_by("-period_start")
        .first()
    )
    if period is None:
        period = BillingPeriod.objects.create(
            account=account,
            organization=org,
            period_start=now,
            period_end=now + timedelta(days=PERIOD_DAYS),
        )
    return period
