"""Clerk webhook endpoint — receives organization and membership events.

Rate limiting is applied as defense-in-depth; Svix signature verification
(via ``verify_webhook``) is the primary protection against abuse.
"""

import json

from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from scoped.logging import get_logger

from plane.webhooks import handlers
from plane.webhooks.ratelimit import webhook_rate_limit

logger = get_logger("plane.webhooks.views")

EVENT_HANDLERS = {
    "organization.created": handlers.handle_organization_created,
    "organization.updated": handlers.handle_organization_updated,
    "organization.deleted": handlers.handle_organization_deleted,
    "organizationMembership.created": handlers.handle_membership_created,
    "organizationMembership.updated": handlers.handle_membership_updated,
    "organizationMembership.deleted": handlers.handle_membership_deleted,
}


@csrf_exempt
@require_POST
@webhook_rate_limit(max_requests=60, window_seconds=60)
def clerk_webhook(request):
    """Receive and dispatch Clerk webhook events."""
    from plane.webhooks.verification import verify_webhook

    try:
        payload = verify_webhook(request.body, request.headers)
    except Exception:
        return HttpResponse("Invalid signature", status=400)

    event_type = payload.get("type", "")
    data = payload.get("data", {})

    handler = EVENT_HANDLERS.get(event_type)
    if handler is None:
        logger.debug(f"Ignoring unhandled webhook event: {event_type}")
        return JsonResponse({"status": "ignored"})

    try:
        handler(data)
    except Exception:
        logger.exception("Webhook handler failed", event_type=event_type)
        return HttpResponse("Handler error", status=500)

    return JsonResponse({"status": "ok"})
