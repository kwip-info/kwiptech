"""Billing views — checkout, portal, billing overview."""

import stripe

from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render
from scoped.logging import get_logger

from plane.billing.models import BillingPeriod, Plan
from plane.billing.stripe_client import get_stripe
from plane.dashboard.views import require_permission

logger = get_logger("plane.billing.views")


@require_permission("billing.manage")
def create_checkout_session(request):
    """Create a Stripe Checkout Session for upgrading to Pro."""
    if request.method != "POST":
        return redirect("dashboard:billing")

    org = request.organization
    stripe = get_stripe()
    if stripe is None:
        messages.error(request, "Billing is not configured.")
        return redirect("dashboard:billing")

    pro_plan = Plan.objects.filter(id="pro").first()
    if pro_plan is None or not pro_plan.stripe_base_price_id:
        messages.error(request, "Pro plan is not available yet.")
        return redirect("dashboard:billing")

    # Ensure Stripe Customer exists
    if not org.stripe_customer_id:
        from plane.billing.stripe_client import create_customer
        create_customer(org)
        org.refresh_from_db()

    if not org.stripe_customer_id:
        messages.error(request, "Could not create billing account.")
        return redirect("dashboard:billing")

    line_items = [{"price": pro_plan.stripe_base_price_id, "quantity": 1}]
    if pro_plan.stripe_object_price_id:
        line_items.append({"price": pro_plan.stripe_object_price_id})
    if pro_plan.stripe_principal_price_id:
        line_items.append({"price": pro_plan.stripe_principal_price_id})

    try:
        session = stripe.checkout.Session.create(
            customer=org.stripe_customer_id,
            mode="subscription",
            line_items=line_items,
            success_url=request.build_absolute_uri("/dashboard/billing/success/"),
            cancel_url=request.build_absolute_uri("/dashboard/billing/"),
            metadata={"org_id": org.id},
        )
        return redirect(session.url)
    except stripe.StripeError:
        logger.exception("Failed to create Stripe Checkout Session")
        messages.error(request, "Could not start checkout. Please try again.")
        return redirect("dashboard:billing")


def checkout_success(request):
    """Landing page after successful Stripe Checkout."""
    messages.success(request, "Welcome to Pro! Your subscription is active.")
    return redirect("dashboard:billing")


@require_permission("billing.manage")
def customer_portal(request):
    """Create a Stripe Customer Portal session and redirect."""
    org = request.organization
    stripe = get_stripe()

    if stripe is None or not org.stripe_customer_id:
        messages.error(request, "Billing is not configured.")
        return redirect("dashboard:billing")

    try:
        session = stripe.billing_portal.Session.create(
            customer=org.stripe_customer_id,
            return_url=request.build_absolute_uri("/dashboard/billing/"),
        )
        return redirect(session.url)
    except stripe.StripeError:
        logger.exception("Failed to create Stripe Portal Session")
        messages.error(request, "Could not open billing portal.")
        return redirect("dashboard:billing")


@require_permission("billing.view")
def billing_overview(request):
    """Billing dashboard — plan, usage, upgrade/manage buttons."""
    org = request.organization
    plan_id = org.plan if org else "free"
    plan_obj = Plan.objects.filter(id=plan_id).first()

    period = (
        BillingPeriod.objects
        .filter(organization=org, finalized=False)
        .order_by("-period_start")
        .first()
    ) if org else None

    return render(request, "dashboard/billing.html", {
        "page_title": "Billing",
        "page_subtitle": "Plan and usage",
        "plan": plan_obj,
        "plan_id": plan_id,
        "period": period,
        "org": org,
    })
