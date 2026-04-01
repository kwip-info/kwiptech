"""Svix webhook signature verification for Clerk webhooks."""

import logging

from django.conf import settings

logger = logging.getLogger(__name__)


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
