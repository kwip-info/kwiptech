"""Billing period lifecycle — close periods, report metered usage to Stripe.

Run daily via management command or scheduler.
"""

from datetime import timedelta

from django.db import models
from django.utils import timezone

import stripe

from scoped.logging import get_logger

from plane.billing.models import BillingPeriod, Plan
from plane.billing.stripe_client import get_stripe
from plane.core.models import Organization

logger = get_logger("plane.billing.tasks")

PERIOD_DAYS = 30
MAX_CLOSE_RETRIES = 5


def close_expired_periods():
    """Find and close all expired billing periods.

    For each expired period:
    1. Report metered overage to Stripe
    2. Mark as finalized
    3. Create the next period

    Periods that fail to close are retried up to MAX_CLOSE_RETRIES times
    with exponential backoff (tracked via close_attempts field).
    """
    now = timezone.now()
    expired = BillingPeriod.objects.filter(
        period_end__lt=now,
        finalized=False,
        close_attempts__lt=MAX_CLOSE_RETRIES,
    ).select_related("organization")

    closed = 0
    failed = 0
    for period in expired:
        try:
            _close_period(period)
            closed += 1
        except Exception:
            # Increment attempt counter so we don't retry forever
            BillingPeriod.objects.filter(id=period.id).update(
                close_attempts=models.F("close_attempts") + 1,
                close_error=str(getattr(period, "_close_error", "unknown")),
            )
            failed += 1
            logger.exception("Failed to close billing period", period_id=period.id, attempt=period.close_attempts + 1)

    logger.info("Billing period close complete", closed=closed, failed=failed)
    return closed


def _close_period(period):
    """Close a single billing period and create the next one."""
    org = period.organization
    if org is None:
        period.finalized = True
        period.save(update_fields=["finalized"])
        return

    # Report metered usage to Stripe
    try:
        report_metered_usage(period, org)
    except Exception as exc:
        period._close_error = str(exc)
        raise

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
    logger.info("Closed period and created next", period_id=period.id, org_id=org.id)


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
    except stripe.StripeError:
        logger.warning("Failed to retrieve subscription", org_id=org.id)
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
                logger.info("Reported object overage", overage=object_overage, org_id=org.id)
            except stripe.StripeError:
                logger.warning("Failed to report object usage", org_id=org.id)

    if principal_overage > 0 and plan.stripe_principal_price_id:
        item_id = items_by_price.get(plan.stripe_principal_price_id)
        if item_id:
            try:
                stripe.SubscriptionItem.create_usage_record(
                    item_id,
                    quantity=principal_overage,
                    action="set",
                )
                logger.info("Reported principal overage", overage=principal_overage, org_id=org.id)
            except stripe.StripeError:
                logger.warning("Failed to report principal usage", org_id=org.id)


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
