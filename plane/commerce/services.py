"""Local delivery accounting; Stripe is asynchronous and never the quota authority."""
import json
import math
import uuid
from datetime import datetime, timedelta, timezone as dt_timezone
from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from plane.access.errors import Problem
from plane.access.auth import refresh_principal
from .models import BillingAccount, Delivery, MeterOutbox


def option(name, default=None):
    return getattr(settings, 'MARKET_' + name, default)


def calendar_period(now):
    start = now.astimezone(dt_timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start, end


def account_for(workspace):
    account, _ = BillingAccount.objects.get_or_create(workspace=workspace)
    return account


def pro_active(account, now=None):
    now = now or timezone.now()
    return bool(account.status == 'active' and account.period_start and account.period_end and account.period_start <= now < account.period_end)


def period_for(account, now):
    if pro_active(account, now):
        return account.allowance_start or account.period_start, account.period_end, option('PRO_CREDITS', 100000)
    start, end = calendar_period(now)
    return start, end, option('FREE_CREDITS', 1000)


def counters(account, now):
    start, end, allowance = period_for(account, now)
    totals = Delivery.objects.filter(workspace_id=account.workspace_id, created_at__gte=start, created_at__lt=end).aggregate(credits=Sum('credits'), overage=Sum('overage_credits'))
    return start, end, allowance, totals['credits'] or 0, totals['overage'] or 0


def usage_summary(workspace):
    account = account_for(workspace)
    now = timezone.now()
    start, end, allowance, used, overage = counters(account, now)
    rate = option('OVERAGE_CENTS_PER_10000', 100)
    return {'plan': 'pro' if pro_active(account, now) else 'free', 'subscription_status': account.status,
            'period_start': start.isoformat(), 'period_end': end.isoformat(), 'included_credits': allowance,
            'used_credits': used, 'remaining_credits': max(0, allowance - used), 'overage_credits': overage,
            'estimated_overage_cents': (overage * rate + 9999) // 10000,
            'overage_enabled': account.overage_enabled, 'spend_cap_cents': account.spend_cap_cents,
            'overage_cents_per_10000': rate, 'pro_monthly_cents': option('PRO_MONTHLY_CENTS', 2900),
            'currency': 'usd', 'billing_account_exists': bool(account.stripe_customer_id), 'billing_enabled': bool(option('BILLING_ENABLED', False)),
            'pricing_status': 'draft' if not option('BILLING_ENABLED', False) else 'configured'}


def available_data():
    from plane.catalog.models import RecordVersion
    # Data must belong to a published dataset and an approved, active source.
    from django.db.models import OuterRef, Subquery
    latest = RecordVersion.objects.filter(record_id=OuterRef('record_id')).order_by('-id').values('id')[:1]
    return RecordVersion.objects.filter(id=Subquery(latest), tombstone=False,
        record__dataset__status='published', record__source__active=True,
        record__source__rights_status='approved').exists()


def deliver(principal, dataset, request_id, request_fingerprint, producer, max_credits=None):
    if not isinstance(request_id, str) or not 1 <= len(request_id) <= 200:
        raise Problem('idempotency_required', 'Provide a stable Idempotency-Key of 1–200 characters.')
    if not isinstance(request_fingerprint, str) or not 1 <= len(request_fingerprint) <= 128:
        raise Problem('invalid_fingerprint', 'Invalid request fingerprint.')
    if max_credits is not None and (type(max_credits) is not int or max_credits < 0):
        raise Problem('invalid_budget', 'max_credits must be a nonnegative integer.')
    with transaction.atomic():
        # Lock the always-existing workspace before first account insertion as well.
        principal = refresh_principal(principal, lock=True)
        workspace = principal.workspace
        principal.require('datasets:read', dataset=dataset.slug)
        account = account_for(workspace)
        from plane.catalog.models import Dataset
        dataset = Dataset.objects.select_for_update().get(pk=dataset.pk)
        if dataset.status != 'published':
            raise Problem('dataset_unavailable', 'This dataset is not available.', 410)
        if principal.key and principal.key.dataset_slugs and dataset.slug not in principal.key.dataset_slugs:
            raise Problem('dataset_forbidden', 'This key cannot access this dataset.', 403)
        previous = Delivery.objects.filter(workspace=workspace, request_id=request_id).first()
        if previous:
            if previous.fingerprint != request_fingerprint or previous.dataset_slug != dataset.slug:
                raise Problem('idempotency_conflict', 'That request ID was used for a different request.', 409)
            if not previous.response or timezone.now() - previous.created_at >= timedelta(hours=24):
                raise Problem('receipt_expired', 'Cached delivery expired; this request ID cannot be reused.', 410)
            source_slugs = {row.get('source', {}).get('slug') for row in previous.response.get('records', [])}
            allowed = set(dataset.sources.filter(active=True, rights_status='approved', slug__in=[s for s in source_slugs if s]).values_list('slug', flat=True))
            if source_slugs - allowed:
                raise Problem('source_unavailable', 'A source in this delivery is no longer available.', 410)
            if principal.key and principal.key.source_slugs and source_slugs - set(principal.key.source_slugs):
                raise Problem('source_forbidden', 'This key cannot access a source in the delivery.', 403)
            return previous.response
        now = timezone.now()
        start, end, allowance, used, prior_overage = counters(account, now)
        result = producer()
        if not isinstance(result, dict) or not isinstance(result.get('records'), list):
            raise Problem('invalid_delivery', 'The dataset response is invalid.', 503)
        source_slugs = {row.get('source', {}).get('slug') for row in result['records'] if isinstance(row, dict)}
        if principal.key and principal.key.source_slugs and source_slugs - set(principal.key.source_slugs):
            raise Problem('source_forbidden', 'This key cannot access a source in the response.', 403)
        count = len(result['records'])
        credits = count * dataset.credits_per_record
        if max_credits is not None and credits > max_credits:
            raise Problem('request_budget_exceeded', 'This request exceeds max_credits.', 402, required_credits=credits)
        overage = max(0, used + credits - allowance) - max(0, used - allowance)
        rate = option('OVERAGE_CENTS_PER_10000', 100)
        if overage:
            if not (pro_active(account, now) and account.overage_enabled and account.metered_item_active and account.stripe_customer_id and option('BILLING_ENABLED', False)):
                raise Problem('quota_exceeded', 'Included credits exhausted. Overage requires Pro and explicit consent.', 402)
            projected_cents = ((prior_overage + overage) * rate + 9999) // 10000
            if projected_cents > account.spend_cap_cents:
                raise Problem('spend_cap_exceeded', 'This request exceeds your monthly overage cap.', 402)
        receipt_id = uuid.uuid4()
        response = dict(result)
        response['usage'] = {'receipt_id': str(receipt_id), 'credits': credits, 'overage_credits': overage,
                             'records': count, 'remaining_credits': max(0, allowance - used - credits)}
        try:
            encoded = json.dumps(response, ensure_ascii=False, allow_nan=False).encode()
        except (ValueError, TypeError, RecursionError) as exc:
            raise Problem('invalid_delivery', 'The dataset response cannot be serialized.', 503) from exc
        if len(encoded) > option('MAX_DELIVERY_BYTES', 1048576):
            raise Problem('response_too_large', 'Use a smaller page size; delivery exceeds 1 MiB.', 413)
        delivery = Delivery.objects.create(id=receipt_id, workspace=workspace, dataset_slug=dataset.slug,
            request_id=request_id, fingerprint=request_fingerprint, response=response, records=count,
            credits=credits, overage_credits=overage, pricing_cents_per_10000=rate, period_start=start, period_end=end)
        if overage:
            MeterOutbox.objects.create(delivery=delivery, customer_id=account.stripe_customer_id,
                                       event_name=option('STRIPE_METER_EVENT', 'kwip_overage_credits'))
        return response


def unix_datetime(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError('Invalid timestamp')
    return datetime.fromtimestamp(value, dt_timezone.utc)
