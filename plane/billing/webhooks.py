"""Stripe webhook handler — subscription lifecycle events.

Idempotent: each Stripe event ID is recorded in StripeEvent before
processing. Duplicate deliveries are silently acknowledged.
"""

import logging

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from plane.billing.models import StripeEvent
from plane.core.models import Organization

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def stripe_webhook(request):
    """Receive and dispatch Stripe webhook events."""
    from plane.billing.stripe_client import get_stripe

    stripe = get_stripe()
    if stripe is None:
        return HttpResponse("Stripe not configured", status=400)

    sig = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(
            request.body,
            sig,
            settings.STRIPE_WEBHOOK_SECRET,
        )
    except Exception:
        logger.warning("Stripe webhook signature verification failed")
        return HttpResponse("Invalid signature", status=400)

    # Idempotency: skip if already processed
    event_id = event.get("id", "")
    if StripeEvent.objects.filter(id=event_id).exists():
        return JsonResponse({"status": "duplicate"})

    handler = EVENT_HANDLERS.get(event["type"])
    if handler is None:
        # Record unhandled events too (prevents reprocessing on retry)
        StripeEvent.objects.create(id=event_id, event_type=event["type"])
        return JsonResponse({"status": "ignored"})

    try:
        handler(event["data"]["object"])
        StripeEvent.objects.create(id=event_id, event_type=event["type"])
    except Exception:
        logger.exception("Stripe webhook handler failed for %s", event["type"])
        # Don't record — allow Stripe to retry
        return HttpResponse("Handler error", status=500)

    return JsonResponse({"status": "ok"})


def _audit_billing_change(org, action, before, after):
    """Record billing changes via pyscoped structured logging."""
    from scoped.logging import get_logger
    get_logger("billing").audit(
        f"billing.{action}",
        org_id=org.id, org_name=org.name, before=before, after=after,
    )


def _handle_checkout_completed(session):
    """Activate Pro plan after successful checkout."""
    org_id = session.get("metadata", {}).get("org_id")
    subscription_id = session.get("subscription")
    if not org_id:
        return

    try:
        org = Organization.objects.get(id=org_id)
        old_plan = org.plan
        org.plan = "pro"
        org.stripe_subscription_id = subscription_id
        org.billing_status = "active"
        org.save(update_fields=["plan", "stripe_subscription_id", "billing_status"])
        _audit_billing_change(org, "plan_upgrade", {"plan": old_plan}, {"plan": "pro"})
        logger.info("Activated Pro plan for org %s", org.id)
    except Organization.DoesNotExist:
        logger.warning("Org %s not found for checkout completion", org_id)


def _handle_subscription_updated(subscription):
    """Update billing status on subscription changes."""
    customer_id = subscription.get("customer")
    status = subscription.get("status", "")

    try:
        org = Organization.objects.get(stripe_customer_id=customer_id)
    except Organization.DoesNotExist:
        return

    status_map = {
        "active": "active",
        "past_due": "past_due",
        "canceled": "cancelled",
        "unpaid": "past_due",
        "trialing": "active",
    }
    org.billing_status = status_map.get(status, org.billing_status)
    org.save(update_fields=["billing_status"])


def _handle_subscription_deleted(subscription):
    """Downgrade to Free on subscription cancellation."""
    customer_id = subscription.get("customer")
    try:
        org = Organization.objects.get(stripe_customer_id=customer_id)
        old_plan = org.plan
        org.plan = "free"
        org.stripe_subscription_id = ""
        org.billing_status = "active"
        org.save(update_fields=["plan", "stripe_subscription_id", "billing_status"])
        _audit_billing_change(org, "plan_downgrade", {"plan": old_plan}, {"plan": "free"})
        logger.info("Downgraded org %s to Free", org.id)
    except Organization.DoesNotExist:
        pass


def _handle_invoice_payment_failed(invoice):
    """Mark org as past_due on payment failure.

    Dunning escalation:
    - First failure: past_due (3-day grace, Stripe retries automatically)
    - If billing_status is already past_due: escalate to suspended
      (blocks sync ingest until payment succeeds)
    """
    customer_id = invoice.get("customer")
    try:
        org = Organization.objects.get(stripe_customer_id=customer_id)
        if org.billing_status == "past_due":
            # Already past_due — escalate to suspended
            org.billing_status = "suspended"
            org.save(update_fields=["billing_status"])
            _audit_billing_change(org, "suspended", {"billing_status": "past_due"}, {"billing_status": "suspended"})
            logger.warning("Suspended org %s after repeated payment failure", org.id)
        else:
            org.billing_status = "past_due"
            org.save(update_fields=["billing_status"])
            _audit_billing_change(org, "past_due", {"billing_status": "active"}, {"billing_status": "past_due"})
            logger.warning("Payment failed for org %s, marked past_due", org.id)
    except Organization.DoesNotExist:
        pass


def _handle_invoice_paid(invoice):
    """Clear past_due/suspended status on successful payment."""
    customer_id = invoice.get("customer")
    try:
        org = Organization.objects.get(stripe_customer_id=customer_id)
        if org.billing_status in ("past_due", "suspended"):
            old_status = org.billing_status
            org.billing_status = "active"
            org.save(update_fields=["billing_status"])
            _audit_billing_change(org, "reactivated", {"billing_status": old_status}, {"billing_status": "active"})
            logger.info("Reactivated org %s after payment", org.id)
    except Organization.DoesNotExist:
        pass


EVENT_HANDLERS = {
    "checkout.session.completed": _handle_checkout_completed,
    "customer.subscription.updated": _handle_subscription_updated,
    "customer.subscription.deleted": _handle_subscription_deleted,
    "invoice.payment_failed": _handle_invoice_payment_failed,
    "invoice.paid": _handle_invoice_paid,
}
