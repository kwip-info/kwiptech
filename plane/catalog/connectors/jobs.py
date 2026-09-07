"""Bounded, evaluation-only jobs connector. No discovery-driven network access."""
import hashlib
import json
import math
import re
import ssl
from datetime import date, datetime, timedelta, timezone as dt_timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

import certifi
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone
from django.utils.html import strip_tags

from plane.catalog.models import CollectionRun, CollectionState, Dataset, IngestionBatch, Record, RecordVersion
from plane.catalog.services import aware_datetime, digest, ingest_batch, register_dataset, register_source

MANIFEST = Path(__file__).resolve().parents[1] / 'job_sources.json'
ENDPOINT = 'https://himalayas.app/jobs/api/search?country=US&exclude_worldwide=true&sort=recent'
ROBOTS = 'https://himalayas.app/robots.txt'
USER_AGENT = 'KWIPJobsPOC/1.0 (+https://kwip.tech; contact@kwip.info)'
FIELDS = {
    'title': {'type': 'string', 'required': True},
    'company': {'type': 'string', 'required': True},
    'company_source_id': {'type': 'string'},
    'country': {'type': 'enum', 'values': ['US'], 'required': True},
    'eligibility': {'type': 'enum', 'values': ['explicit_us_remote'], 'required': True},
    'remote': {'type': 'boolean', 'required': True},
    'employment_type': {'type': 'string'},
    'location_restrictions': {'type': 'string', 'required': True},
    'timezone_restrictions': {'type': 'string'},
    'salary_min': {'type': 'number'}, 'salary_max': {'type': 'number'},
    'salary_currency': {'type': 'string'},
    'salary_period': {'type': 'enum', 'values': ['hourly', 'weekly', 'fortnightly', 'monthly', 'annual']},
    'published_at': {'type': 'datetime'}, 'expires_at': {'type': 'datetime'},
    'source_status': {'type': 'enum', 'values': ['listed', 'past_source_expiry'], 'required': True},
    'normalization_version': {'type': 'integer', 'required': True},
}


class CollectionError(Exception):
    def __init__(self, code, retry_after=None):
        self.code, self.retry_after = code, retry_after
        super().__init__(code)


def manifest():
    return json.loads(MANIFEST.read_text())


def policy(source_id='himalayas', now=None):
    now = now or timezone.now()
    data = manifest()
    source = next((s for s in data['sources'] if s['id'] == source_id), None)
    if not source or source.get('status') != 'evaluation' or source.get('adapter') != 'himalayas_us_v1':
        raise CollectionError('source_not_enabled_for_evaluation')
    if date.fromisoformat(source['review_due_on']) <= now.date():
        raise CollectionError('source_policy_review_due')
    # A manifest edit cannot turn the bounded POC into an arbitrary crawler.
    if (source['endpoint'] != ENDPOINT or source['robots_url'] != ROBOTS
            or source['customer_access'] is not False or source['exports'] is not False
            or source['max_data_requests'] != 1 or source['max_records'] != 20
            or source['minimum_refresh_hours'] < 24 or source['retention_days'] != 7
            or source['max_response_bytes'] != 2_000_000):
        raise CollectionError('unsupported_collection_policy')
    return source


def timestamp(value):
    if value is None or value == '':
        return None
    try:
        if type(value) in (int, float):
            if not math.isfinite(value) or value < 0:
                raise ValueError
            parsed = datetime.fromtimestamp(value / 1000 if value >= 1e12 else value, dt_timezone.utc)
        else:
            parsed = aware_datetime(value)
        return parsed.astimezone(dt_timezone.utc).isoformat()
    except (ValueError, OverflowError, OSError, ValidationError):
        raise CollectionError('invalid_source_timestamp') from None


def text(value, limit=500):
    if not isinstance(value, str):
        raise CollectionError('invalid_source_text')
    value = ' '.join(strip_tags(value).split())
    if not value or len(value) > limit:
        raise CollectionError('invalid_source_text')
    return value


def source_link(job):
    for value in (job.get('applicationLink'), job.get('guid')):
        if not isinstance(value, str) or len(value) > 2000:
            continue
        try:
            u = urlsplit(value)
            if u.scheme == 'https' and u.hostname in ('himalayas.app', 'www.himalayas.app') and not u.username and not u.password and u.port in (None, 443) and u.path.startswith('/companies/'):
                return value
        except ValueError:
            pass
    raise CollectionError('missing_provider_attribution_link')


def normalize(job, observed_at):
    if not isinstance(job, dict):
        raise CollectionError('invalid_job_object')
    locations = job.get('locationRestrictions')
    if not isinstance(locations, list) or not all(isinstance(v, str) for v in locations):
        raise CollectionError('unverified_us_eligibility')
    if not any(v.strip().casefold() in ('us', 'usa', 'united states', 'united states of america') for v in locations):
        raise CollectionError('unverified_us_eligibility')
    payload = {'title': text(job.get('title'), 300), 'company': text(job.get('companyName'), 300),
               'country': 'US', 'eligibility': 'explicit_us_remote', 'remote': True,
               'location_restrictions': text('; '.join(locations), 2000),
               'source_status': 'listed', 'normalization_version': 1}
    for upstream, field in (('companySlug', 'company_source_id'), ('employmentType', 'employment_type')):
        if job.get(upstream):
            payload[field] = text(job[upstream])
    zones = job.get('timezoneRestriction')
    if zones:
        if not isinstance(zones, list) or not all(type(v) in (str, int, float) for v in zones):
            raise CollectionError('invalid_timezone_restrictions')
        payload['timezone_restrictions'] = text('; '.join(map(str, zones)), 2000)
    # Keep amount, currency and period together; never silently annualize pay.
    amounts = {k: job.get(v) for k, v in (('salary_min', 'minSalary'), ('salary_max', 'maxSalary')) if job.get(v) is not None}
    if amounts:
        if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1e12 for v in amounts.values()):
            raise CollectionError('invalid_salary')
        if amounts.get('salary_min', 0) > amounts.get('salary_max', 1e12):
            raise CollectionError('invalid_salary_range')
        currency, period = job.get('currency'), job.get('salaryPeriod')
        if isinstance(currency, str) and re.fullmatch('[A-Z]{3}', currency) and period in FIELDS['salary_period']['values']:
            payload.update(amounts, salary_currency=currency, salary_period=period)
    for upstream, field in (('pubDate', 'published_at'), ('expiryDate', 'expires_at')):
        value = timestamp(job.get(upstream))
        if value:
            payload[field] = value
    if payload.get('expires_at') and aware_datetime(payload['expires_at']) <= aware_datetime(observed_at):
        payload['source_status'] = 'past_source_expiry'
    result = {'external_id': text(job.get('guid'), 500), 'payload': payload,
              'observed_at': observed_at, 'source_url': source_link(job)}
    if payload.get('published_at'):
        result['effective_at'] = payload['published_at']
    return result


def normalize_response(data, observed_at):
    if not isinstance(data, dict) or not isinstance(data.get('jobs'), list):
        raise CollectionError('unexpected_response_schema')
    items, rejected, seen = [], {}, set()
    for job in data['jobs'][:20]:
        try:
            item = normalize(job, observed_at)
            if item['external_id'] in seen:
                raise CollectionError('duplicate_source_id')
            seen.add(item['external_id'])
            items.append(item)
        except CollectionError as exc:
            rejected[exc.code] = rejected.get(exc.code, 0) + 1
    summary = {'received': len(data['jobs']), 'examined': min(20, len(data['jobs'])),
               'accepted': len(items), 'rejected': rejected, 'sample_only': True,
               'normalization_version': 1}
    for key in ('lastUpdated', 'updatedAt'):
        if data.get(key) is not None:
            try:
                summary['provider_updated_at'] = timestamp(data[key])
            except CollectionError:
                summary['provider_timestamp_invalid'] = True
    return items, summary


def robots_allowed(body, url, agent=USER_AGENT):
    """Evaluate matching groups and longest Allow/Disallow, including * and $."""
    product = agent.split('/', 1)[0].split(' ', 1)[0].lower()
    groups, agents, rules, delay = [], [], [], 0
    for line in body.splitlines() + ['User-agent: _end']:
        line = line.split('#', 1)[0].strip()
        if ':' not in line:
            continue
        key, value = (x.strip() for x in line.split(':', 1))
        key = key.lower()
        if key == 'user-agent':
            if rules or delay:
                groups.append((agents, rules, delay))
                agents, rules, delay = [], [], 0
            agents.append(value.lower())
        elif key in ('allow', 'disallow') and agents:
            if value:
                rules.append((key, value))
        elif key == 'crawl-delay' and agents:
            try:
                delay = max(delay, float(value))
                if not math.isfinite(delay) or delay < 0:
                    raise ValueError
            except ValueError:
                raise CollectionError('invalid_robots_delay') from None
    matches = []
    for names, rules, delay in groups:
        specificity = max((0 if n == '*' else len(n) for n in names if n == '*' or n in product), default=-1)
        if specificity >= 0:
            matches.append((specificity, rules, delay))
    if not matches:
        return True, 0
    best = max(m[0] for m in matches)
    path = urlsplit(url).path + ('?' + urlsplit(url).query if urlsplit(url).query else '')
    decisions, gap = [], 0
    for specificity, rules, delay in matches:
        if specificity != best:
            continue
        gap = max(gap, delay)
        for key, pattern in rules:
            terminal = pattern.endswith('$')
            pattern = pattern[:-1] if terminal else pattern
            regex = '^' + '.*'.join(re.escape(p) for p in pattern.split('*')) + ('$' if terminal else '')
            if re.search(regex, path):
                decisions.append((len(pattern.replace('*', '').encode()), key == 'allow'))
    return (max(decisions)[1] if decisions else True), gap


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http_get(url, max_bytes):
    if url not in (ROBOTS, ENDPOINT):
        raise CollectionError('endpoint_not_allowlisted')
    opener = build_opener(NoRedirect(), HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where())))
    request = Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'text/plain' if url == ROBOTS else 'application/json', 'Accept-Encoding': 'identity'})
    try:
        response = opener.open(request, timeout=20)
    except HTTPError as exc:
        response = exc
    except (URLError, TimeoutError, OSError):
        raise CollectionError('network_error') from None
    with response:
        body = response.read(max_bytes + 1)
        if len(body) > max_bytes:
            raise CollectionError('response_too_large')
        return response.status, dict(response.headers), body


def retry_time(headers, now):
    value = next((v for k, v in headers.items() if k.lower() == 'retry-after'), '')
    try:
        return now + timedelta(seconds=max(0, int(value)))
    except (ValueError, OverflowError):
        try:
            result = parsedate_to_datetime(value)
            return result if result.tzinfo else result.replace(tzinfo=dt_timezone.utc)
        except (ValueError, TypeError, OverflowError):
            return now + timedelta(seconds=60)


@transaction.atomic
def prepare_source(p):
    existing, _ = Dataset.objects.get_or_create(slug='us-jobs-poc', defaults={'title': 'US remote jobs · private POC'})
    existing = Dataset.objects.select_for_update().get(pk=existing.pk)
    if existing.status != 'draft':
        raise CollectionError('evaluation_dataset_not_draft')
    dataset = register_dataset({'slug': 'us-jobs-poc', 'title': 'US remote jobs · private POC',
        'description': 'Small attributed current sample. US eligibility does not imply a US employer. No commercial distribution approved.',
        'category': 'Jobs', 'schema_version': 1, 'fields': FIELDS, 'status': 'draft'})
    existing_source = dataset.sources.filter(slug=p['id']).first()
    if existing_source and (existing_source.rights_status != 'evaluation' or not existing_source.active):
        raise CollectionError('source_evaluation_disabled')
    source = register_source(dataset, {'slug': p['id'], 'name': p['name'], 'url': p['attribution_url'],
        'attribution': p['attribution'], 'license_url': p['evidence_urls'][0],
        'rights_status': 'evaluation', 'schema_version': 1})
    CollectionState.objects.get_or_create(source=source)
    return source


def collect(source_id='himalayas', fetch=None, now=None):
    now, fetch = now or timezone.now(), fetch or http_get
    p = policy(source_id, now)
    source = prepare_source(p)
    with transaction.atomic():
        state = CollectionState.objects.select_for_update().get(source=source)
        if state.next_allowed_at and state.next_allowed_at > now:
            return {'status': 'not_due', 'next_allowed_at': state.next_allowed_at.isoformat(), 'data_requests': 0}
        state.next_allowed_at = now + timedelta(hours=p['minimum_refresh_hours'])
        state.save(update_fields=['next_allowed_at'])
        # Committed reservation prevents parallel and crash-retry request storms.
        run = CollectionRun.objects.create(source=source, started_at=now, manifest_hash=digest(p))
    receipt = {'robots_requests': 0, 'data_requests': 0}
    try:
        receipt['robots_requests'] = 1
        status, headers, raw = fetch(ROBOTS, 500_000)
        if status != 200:
            raise CollectionError('robots_unavailable', retry_time(headers, now) if status in (429, 503) else None)
        receipt['robots_sha256'] = hashlib.sha256(raw).hexdigest()
        allowed, delay = robots_allowed(raw.decode('utf-8'), ENDPOINT)
        if not allowed:
            raise CollectionError('robots_disallowed')
        # Avoid unbounded sleeps. A future connector may persist a separate lease.
        if delay > 60:
            raise CollectionError('robots_delay_requires_scheduled_fetch')
        if delay:
            import time
            time.sleep(delay)
        receipt['data_requests'] = 1
        status, headers, raw = fetch(ENDPOINT, p['max_response_bytes'])
        if status != 200:
            raise CollectionError('upstream_http_' + str(status), retry_time(headers, now) if status in (429, 503) else None)
        data = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        items, summary = normalize_response(data, now.isoformat())
        receipt.update(summary)
        with transaction.atomic():
            # ingester rechecks active/evaluation rights and draft state after fetch.
            batch_result = ingest_batch(source, items, 'jobs-poc:' + str(run.pk)) if items else None
            state = CollectionState.objects.select_for_update().get(source=source)
            state.last_success_batch_id = batch_result['batch_id'] if batch_result else None
            state.save(update_fields=['last_success_batch'])
            run.status = 'complete'
            run.summary = receipt
            run.finished_at = timezone.now()
            run.save()
        return {'status': 'complete', 'run_id': run.pk, **receipt}
    except Exception as exc:
        code = exc.code if isinstance(exc, CollectionError) else 'invalid_response_or_ingestion_failed'
        with transaction.atomic():
            state = CollectionState.objects.select_for_update().get(source=source)
            if isinstance(exc, CollectionError) and exc.retry_after and exc.retry_after > state.next_allowed_at:
                state.next_allowed_at = exc.retry_after
                state.save(update_fields=['next_allowed_at'])
            run.status, run.finished_at = 'failed', timezone.now()
            run.summary = receipt | {'error': code}
            run.save()
        raise CollectionError(code) from None


@transaction.atomic
def purge_expired(now=None):
    """Only this evaluation dataset; never delete approved marketplace history."""
    now = now or timezone.now()
    dataset = Dataset.objects.select_for_update().filter(slug='us-jobs-poc').first()
    if not dataset:
        return 0
    # Retention follows collection provenance even after revocation/publication.
    # Only batches made by this connector expire, never other marketplace history.
    batches = IngestionBatch.objects.filter(source__dataset=dataset, idempotency_key__startswith='jobs-poc:')
    ids = list(RecordVersion.objects.filter(batch__in=batches, created_at__lt=now - timedelta(days=7)).values_list('id', flat=True)[:500])
    RecordVersion.objects.filter(id__in=ids).delete()
    empty_batches = batches.annotate(has_rows=Exists(RecordVersion.objects.filter(batch_id=OuterRef('pk')))).filter(has_rows=False)
    empty_batches.delete()
    empty_records = Record.objects.filter(dataset=dataset).annotate(has_rows=Exists(RecordVersion.objects.filter(record_id=OuterRef('pk')))).filter(has_rows=False)
    empty_records.delete()
    return len(ids)


def preview(now=None):
    now = now or timezone.now()
    data = manifest()
    result = {'sources': data['sources'], 'discovery': data['discovery'], 'records': [], 'runs': [], 'private': True,
              'notice': 'Private evaluation · current sample only · no customer access or exports'}
    try:
        p = policy(now=now)
    except CollectionError as exc:
        result['notice'] = exc.code.replace('_', ' ') + ' — sample hidden until reviewed.'
        return result
    source = Dataset.objects.filter(slug='us-jobs-poc', status='draft').first()
    source = source.sources.filter(slug=p['id'], rights_status='evaluation', active=True).first() if source else None
    if not source:
        return result
    state = CollectionState.objects.filter(source=source).first()
    result['next_allowed_at'] = state.next_allowed_at.isoformat() if state and state.next_allowed_at else None
    result['runs'] = [{'id': r.pk, 'status': r.status, 'started_at': r.started_at.isoformat(), 'summary': r.summary} for r in source.collection_runs.order_by('-id')[:10]]
    if state and state.last_success_batch_id:
        rows = RecordVersion.objects.filter(batch_id=state.last_success_batch_id, created_at__gte=now - timedelta(days=7)).select_related('record').order_by('id')[:20]
        result['records'] = [{'id': r.record.external_id, 'data': r.payload, 'source_url': r.source_url,
                              'source': r.source_metadata, 'observed_at': r.observed_at.isoformat(), 'content_hash': r.content_hash} for r in rows]
    result['summary'] = {'records': len(result['records']),
                         'companies': len({r['data'].get('company_source_id', r['data']['company']) for r in result['records']}),
                         'with_pay': sum('salary_currency' in r['data'] for r in result['records'])}
    return result
