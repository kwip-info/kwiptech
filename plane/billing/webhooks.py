"""Stripe webhook handler — subscription lifecycle events."""

import logging

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

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

    handler = EVENT_HANDLERS.get(event["type"])
    if handler is None:
        return JsonResponse({"status": "ignored"})

    try:
        handler(event["data"]["object"])
    except Exception:
        logger.exception("Stripe webhook handler failed for %s", event["type"])
        return HttpResponse("Handler error", status=500)

    return JsonResponse({"status": "ok"})


def _handle_checkout_completed(session):
    """Activate Pro plan after successful checkout."""
    org_id = session.get("metadata", {}).get("org_id")
    subscription_id = session.get("subscription")
    if not org_id:
        return

    try:
        org = Organization.objects.get(id=org_id)
        org.plan = "pro"
        org.stripe_subscription_id = subscription_id
        org.billing_status = "active"
        org.save(update_fields=["plan", "stripe_subscription_id", "billing_status"])
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
        org.plan = "free"
        org.stripe_subscription_id = ""
        org.billing_status = "active"
        org.save(update_fields=["plan", "stripe_subscription_id", "billing_status"])
        logger.info("Downgraded org %s to Free", org.id)
    except Organization.DoesNotExist:
        pass


def _handle_invoice_payment_failed(invoice):
    """Mark org as past_due on payment failure."""
    customer_id = invoice.get("customer")
    try:
        org = Organization.objects.get(stripe_customer_id=customer_id)
        org.billing_status = "past_due"
        org.save(update_fields=["billing_status"])
        logger.warning("Payment failed for org %s", org.id)
    except Organization.DoesNotExist:
        pass


def _handle_invoice_paid(invoice):
    """Clear past_due status on successful payment."""
    customer_id = invoice.get("customer")
    try:
        org = Organization.objects.get(stripe_customer_id=customer_id)
        if org.billing_status == "past_due":
            org.billing_status = "active"
            org.save(update_fields=["billing_status"])
    except Organization.DoesNotExist:
        pass


EVENT_HANDLERS = {
    "checkout.session.completed": _handle_checkout_completed,
    "customer.subscription.updated": _handle_subscription_updated,
    "customer.subscription.deleted": _handle_subscription_deleted,
    "invoice.payment_failed": _handle_invoice_payment_failed,
    "invoice.paid": _handle_invoice_paid,
}
