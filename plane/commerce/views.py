import stripe
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.core.exceptions import RequestDataTooBig
from plane.access.http import endpoint, body_json
from plane.access.errors import Problem
from plane.access.models import Workspace
from .services import account_for, usage_summary, pro_active, option
from . import stripe_gateway
from .models import BillingConsent


@endpoint()
def usage(request, principal):
    return usage_summary(principal.workspace)


def provider_response(call):
    try:
        return call()
    except stripe.StripeError as exc:
        raise Problem('billing_provider_unavailable', 'Billing provider is unavailable. Please retry.', 503) from exc


@endpoint(methods=('POST',))
def checkout(request, principal):
    principal.require_browser()
    return provider_response(lambda: stripe_gateway.checkout(principal.workspace))


@endpoint(methods=('POST',))
def portal(request, principal):
    principal.require_browser()
    return provider_response(lambda: stripe_gateway.portal(principal.workspace))


@endpoint(methods=('POST',))
def configure_overage(request, principal):
    principal.require_browser()
    data = body_json(request)
    enabled, cap = data.get('enabled'), data.get('spend_cap_cents')
    if type(enabled) is not bool or type(cap) is not int or not 0 <= cap <= 100000:
        raise Problem('invalid_spend_cap', 'Set enabled to a boolean and spend_cap_cents between 0 and 100000.')
    if enabled:
        stripe_gateway.require_sales()
    with transaction.atomic():
        Workspace.objects.select_for_update().get(pk=principal.workspace.pk)
        account = account_for(principal.workspace)
        if enabled and (not pro_active(account) or not account.metered_item_active or cap == 0):
            raise Problem('pro_required', 'An active Pro subscription and a positive spend cap are required.', 409)
        account.overage_enabled, account.spend_cap_cents = enabled, cap
        account.save(update_fields=['overage_enabled', 'spend_cap_cents'])
        BillingConsent.objects.create(workspace=principal.workspace, identity=principal.workspace.owner,
            overage_enabled=enabled, spend_cap_cents=cap, overage_cents_per_10000=option('OVERAGE_CENTS_PER_10000', 100))
    return usage_summary(principal.workspace)


@csrf_exempt
def webhook(request):
    if request.method != 'POST':
        return JsonResponse({'error': {'code': 'method_not_allowed'}}, status=405, headers={'Allow': 'POST', 'Cache-Control': 'no-store'})
    try:
        if int(request.META.get('CONTENT_LENGTH') or 0) > 1048576:
            raise Problem('body_too_large', 'Webhook exceeds allowed size.', 413)
        body = request.body
        if len(body) > 1048576:
            raise Problem('body_too_large', 'Webhook exceeds allowed size.', 413)
        stripe_gateway.receive_event(body, request.headers.get('Stripe-Signature', ''))
        response = JsonResponse({'received': True})
    except (ValueError, RequestDataTooBig):
        response = JsonResponse({'error': {'code': 'invalid_body'}}, status=400)
    except Problem as exc:
        response = JsonResponse({'error': {'code': exc.code, 'message': exc.message}}, status=exc.status)
    response['Cache-Control'] = 'no-store'
    return response
