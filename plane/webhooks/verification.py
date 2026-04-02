"""Svix webhook signature verification for Clerk webhooks."""

from django.conf import settings
from scoped.logging import get_logger

logger = get_logger("plane.webhooks.verification")


def verify_webhook(payload_bytes, headers):
    """Verify the Svix signature on a Clerk webhook payload.

    Returns the parsed payload dict on success, raises on failure.
    """
    from svix.webhooks import Webhook, WebhookVerificationError

    secret = settings.CLERK_WEBHOOK_SECRET
    if not secret:
        raise ValueError("CLERK_WEBHOOK_SECRET is not configured")

    wh = Webhook(secret)
    try:
        return wh.verify(payload_bytes, {
            "svix-id": headers.get("svix-id", ""),
            "svix-timestamp": headers.get("svix-timestamp", ""),
            "svix-signature": headers.get("svix-signature", ""),
        })
    except WebhookVerificationError:
        logger.warning("Webhook signature verification failed")
        raise
