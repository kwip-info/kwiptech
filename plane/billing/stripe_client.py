"""Stripe client initialization.

Lazy initialization — only configures Stripe when called.
No-ops gracefully when STRIPE_SECRET_KEY is not set.
"""

import stripe

from django.conf import settings
from scoped.logging import get_logger

logger = get_logger("plane.billing.stripe_client")


def get_stripe():
    """Return the stripe module with API key configured.

    Returns None if STRIPE_SECRET_KEY is not set.
    """
    if not settings.STRIPE_SECRET_KEY:
        return None

    import stripe
    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe


def create_customer(org):
    """Create a Stripe Customer for an organization.

    No-ops if Stripe is not configured or if the org already has a customer.
    """
    if org.stripe_customer_id:
        return

    stripe = get_stripe()
    if stripe is None:
        return

    try:
        customer = stripe.Customer.create(
            name=org.name,
            metadata={"org_id": org.id, "slug": org.slug},
        )
        org.stripe_customer_id = customer.id
        org.save(update_fields=["stripe_customer_id"])
        logger.info("Created Stripe Customer", customer_id=customer.id, org_id=org.id)
    except stripe.StripeError:
        logger.warning("Failed to create Stripe Customer", org_id=org.id)
