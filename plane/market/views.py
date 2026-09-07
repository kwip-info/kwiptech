"""Public marketplace pages and bounded catalog metadata. No implicit data delivery."""
from django.conf import settings
from django.shortcuts import render
from django.http import Http404
from django.db.models import Q
from django.db import transaction
from plane.access.auth import refresh_principal
from django.views.decorators.http import require_safe
from plane.access.http import endpoint, body_json
from plane.access.errors import Problem
from plane.catalog.models import Dataset, Source
from plane.catalog.services import register_dataset, register_source, ingest_batch, read_records, digest


def context():
    issuer = settings.MARKET_CLERK_ISSUER.rstrip('/')
    return {'clerk_key': settings.MARKET_CLERK_PUBLISHABLE_KEY,
            'clerk_script': issuer + '/npm/@clerk/clerk-js@6/dist/clerk.browser.js' if issuer else '',
            'clerk_ui_script': issuer + '/npm/@clerk/ui@1/dist/ui.browser.js' if issuer else '',
            'market_origin': settings.MARKET_ORIGIN}

@require_safe
def page(request, screen='catalog', slug=None):
    if screen == 'dataset' and not published().filter(slug=slug).exists():
        raise Http404('Dataset not found.')
    return render(request, 'market/app.html', context() | {'screen': screen, 'dataset_slug': slug or ''})

def published():
    return Dataset.objects.filter(status='published', sources__active=True, sources__rights_status='approved').distinct()

def get_dataset(slug):
    dataset = published().filter(slug=slug).first()
    if not dataset:
        raise Problem('not_found', 'Dataset not found.', 404)
    return dataset

def dataset_json(dataset, detail=False):
    schema = dataset.schemas.order_by('-version').first()
    data = {'slug': dataset.slug, 'title': dataset.title, 'description': dataset.description,
            'category': dataset.category, 'credits_per_record': dataset.credits_per_record,
            'updated_at': dataset.updated_at.isoformat(), 'url': '/data/' + dataset.slug,
            'schema_version': schema.version if schema else None}
    if detail:
        data['fields'] = schema.fields if schema else {}
        data['sources'] = [{'slug': s.slug, 'name': s.name, 'url': s.url, 'attribution': s.attribution,
                            'license_url': s.license_url} for s in dataset.sources.filter(active=True, rights_status='approved')[:100]]
        data['limits'] = {'page_size': 100, 'filters': 10, 'cursor_lifetime_seconds': 86400}
    return data

@endpoint(authenticated=False)
def datasets(request, principal):
    search = request.GET.get('q', '').strip()
    if len(search) > 100:
        raise Problem('query_too_long', 'Search must be at most 100 characters.')
    query = published()
    if search:
        query = query.filter(Q(title__icontains=search) | Q(description__icontains=search) | Q(category__icontains=search))
    after = request.GET.get('after', '')
    if len(after) > 100:
        raise Problem('invalid_cursor', 'Invalid catalog cursor.')
    if after:
        query = query.filter(slug__gt=after)
    rows = list(query.order_by('slug')[:51])
    return {'datasets': [dataset_json(d) for d in rows[:50]], 'next_after': rows[49].slug if len(rows) > 50 else None}

@endpoint(authenticated=False)
def dataset_detail(request, principal, slug):
    return dataset_json(get_dataset(slug), detail=True)

@endpoint(('POST',))
def query_dataset(request, principal, slug):
    principal.require('datasets:read', dataset=slug)
    data = body_json(request, 32768)
    if set(data) - {'filters', 'fields', 'limit', 'cursor', 'max_credits'}:
        raise Problem('invalid_query', 'Unknown query properties.')
    dataset = get_dataset(slug)
    request_id = request.headers.get('Idempotency-Key', '')
    if not 8 <= len(request_id) <= 200:
        raise Problem('idempotency_key_required', 'Supply an Idempotency-Key of 8–200 characters for record delivery.')
    from plane.commerce.services import deliver
    return deliver(principal, dataset, request_id, digest({'dataset': slug, 'query': data}),
                   lambda: read_records(dataset, filters=data.get('filters'), fields=data.get('fields'),
                                        limit=data.get('limit', 25), cursor=data.get('cursor')), max_credits=data.get('max_credits'))

@endpoint(('POST',))
@transaction.atomic
def register(request, principal):
    principal = refresh_principal(principal, lock=True)
    principal.require('ingest:write')
    principal.require_browser()
    data = body_json(request)
    if set(data) - {'dataset', 'dry_run'}:
        raise Problem('invalid_registration', 'Use dataset and dry_run only.')
    manifest = data.get('dataset')
    dry_run = data.get('dry_run', True)
    if type(dry_run) is not bool:
        raise Problem('invalid_dry_run', 'dry_run must be boolean.')
    dataset = register_dataset(manifest, dry_run=dry_run)
    return {'slug': dataset.slug, 'status': dataset.status, 'dry_run': dry_run}

@endpoint(('POST',))
@transaction.atomic
def source_register(request, principal, slug):
    principal = refresh_principal(principal, lock=True)
    principal.require('ingest:write', dataset=slug)
    principal.require_browser()
    dataset = Dataset.objects.filter(slug=slug).first()
    if not dataset:
        raise Problem('not_found', 'Dataset not found.', 404)
    data = body_json(request)
    dry_run = data.get('dry_run', True)
    if type(dry_run) is not bool:
        raise Problem('invalid_dry_run', 'dry_run must be boolean.')
    if set(data) - {'source', 'dry_run'}:
        raise Problem('invalid_registration', 'Use source and dry_run only.')
    source = register_source(dataset, data.get('source'), dry_run=dry_run)
    return {'slug': source.slug, 'rights_status': source.rights_status, 'dry_run': dry_run}

@endpoint(('POST',))
@transaction.atomic
def ingest(request, principal, slug, source_slug):
    principal = refresh_principal(principal, lock=True)
    principal.require('ingest:write', dataset=slug, source=source_slug)
    source = Source.objects.select_related('dataset').filter(dataset__slug=slug, slug=source_slug).first()
    if not source:
        raise Problem('not_found', 'Source not found.', 404)
    data = body_json(request)
    if set(data) - {'items', 'dry_run'} or type(data.get('dry_run', True)) is not bool:
        raise Problem('invalid_batch', 'Use items and an explicit boolean dry_run.')
    return ingest_batch(source, data.get('items'), request.headers.get('Idempotency-Key', ''), dry_run=data.get('dry_run', True))

@endpoint(authenticated=False)
def plans(request, principal):
    from plane.commerce.services import option, available_data
    return {'free_credits': option('FREE_CREDITS', 1000), 'pro_credits': option('PRO_CREDITS', 100000),
            'pro_monthly_cents': option('PRO_MONTHLY_CENTS', 2900),
            'overage_cents_per_10000': option('OVERAGE_CENTS_PER_10000', 100),
            'currency': 'usd', 'purchases_available': bool(option('BILLING_ENABLED', False) and available_data()),
            'catalog_has_data': available_data()}


@endpoint()
def jobs_poc(request, principal):
    principal = refresh_principal(principal)
    principal.require_browser()
    principal.require('ingest:write', dataset='us-jobs-poc', source='himalayas')
    from plane.catalog.connectors.jobs import preview
    return preview()

@require_safe
def policy(request, kind):
    return render(request, 'market/policy.html', context() | {'kind': kind})
