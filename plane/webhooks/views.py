"""Clerk webhook endpoint — receives organization and membership events."""

import json
import logging

from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from plane.webhooks import handlers

logger = logging.getLogger(__name__)

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
        logger.debug("Ignoring unhandled webhook event: %s", event_type)
        return JsonResponse({"status": "ignored"})

    try:
        handler(data)
    except Exception:
        logger.exception("Webhook handler failed for event %s", event_type)
        return HttpResponse("Handler error", status=500)

    return JsonResponse({"status": "ok"})
