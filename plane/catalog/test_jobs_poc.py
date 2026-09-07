import copy
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone as dt_timezone
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command, CommandError
from django.test import Client
from django.db import close_old_connections, connection

from plane.access.auth import issue_key
from plane.access.models import Identity, Workspace
from plane.catalog.connectors import jobs
from plane.catalog.models import CollectionRun, CollectionState, Dataset, Record, RecordVersion
from plane.catalog.services import ingest_batch, read_records, register_dataset, register_source
from plane.commerce.services import available_data

pytestmark = pytest.mark.django_db
NOW = datetime(2026, 9, 7, 23, tzinfo=dt_timezone.utc)


def sample(**overrides):
    return {'guid': 'invented-001', 'title': 'Data engineer', 'companyName': 'Example Company',
            'companySlug': 'example-company', 'employmentType': 'Full Time',
            'locationRestrictions': ['United States'], 'timezoneRestriction': [-5, -6],
            'minSalary': 100000, 'maxSalary': 120000, 'salaryPeriod': 'annual', 'currency': 'USD',
            'pubDate': '2026-09-06T10:00:00Z', 'expiryDate': '2026-10-06T10:00:00Z',
            'applicationLink': 'https://himalayas.app/companies/example-company/jobs/invented',
            'description': '<script>never stored</script>', 'excerpt': 'copyrighted example',
            'companyLogo': 'https://example.com/logo.png', **overrides}


def transport(*records, robots='User-agent: *\nAllow: /', status=200, headers=None):
    calls = []
    def fetch(url, max_bytes):
        calls.append(url)
        if url == jobs.ROBOTS:
            return 200, {}, robots.encode()
        return status, headers or {}, json.dumps({'jobs': list(records)}).encode()
    fetch.calls = calls
    return fetch


def run(*records, **kwargs):
    fetch = transport(*(records or [sample()]), **kwargs)
    with patch('django.utils.timezone.now', return_value=NOW):
        receipt = jobs.collect(fetch=fetch, now=NOW)
    return receipt, fetch


def test_normalized_sample_and_private_catalog_boundary():
    receipt, fetch = run()
    assert receipt['accepted'] == 1 and fetch.calls == [jobs.ROBOTS, jobs.ENDPOINT]
    row = RecordVersion.objects.get()
    assert row.payload['salary_period'] == 'annual'
    assert row.payload['salary_min'] == 100000
    assert row.payload['country'] == 'US'
    assert not {'description', 'excerpt', 'companyLogo'} & row.payload.keys()
    assert row.source_metadata['name'] == 'Himalayas'
    assert row.source_url.startswith('https://himalayas.app/companies/')
    assert Client().get('/api/v2/datasets').json()['datasets'] == []
    assert Client().get('/api/v2/datasets/us-jobs-poc').status_code == 404
    assert not available_data()
    with pytest.raises(ValidationError):
        read_records(Dataset.objects.get())
    dataset = Dataset.objects.get()
    dataset.status = 'published'
    with pytest.raises(ValidationError):
        dataset.full_clean()
    view = jobs.preview(now=NOW)
    assert view['summary'] == {'records': 1, 'companies': 1, 'with_pay': 1}
    assert view['records'][0]['source']['attribution']


def test_immediate_retry_has_no_network_or_duplicate_observations():
    run()
    fetch = transport(sample())
    receipt = jobs.collect(fetch=fetch, now=NOW + timedelta(minutes=1))
    assert receipt['status'] == 'not_due' and fetch.calls == []
    assert RecordVersion.objects.count() == CollectionRun.objects.count() == 1


def test_next_day_same_id_preserves_observed_change_without_duplicate_identity():
    run()
    fetch = transport(sample(minSalary=110000))
    with patch('django.utils.timezone.now', return_value=NOW + timedelta(days=1)):
        jobs.collect(fetch=fetch, now=NOW + timedelta(days=1))
    assert Record.objects.count() == 1 and RecordVersion.objects.count() == 2
    assert RecordVersion.objects.first().payload['salary_min'] == 100000
    assert jobs.preview(now=NOW + timedelta(days=1))['records'][0]['data']['salary_min'] == 110000


def test_mixed_response_quarantines_bad_rows_and_duplicates():
    receipt, _ = run(sample(), sample(), sample(guid='world', locationRestrictions=[]),
                     sample(guid='uk', locationRestrictions=['United Kingdom']), sample(guid='bad-pay', minSalary=True))
    assert receipt['accepted'] == 1
    assert receipt['rejected'] == {'duplicate_source_id': 1, 'unverified_us_eligibility': 2, 'invalid_salary': 1}


@pytest.mark.parametrize('value', ['javascript:alert(1)', 'https://evil.example/companies/foo', 'https://himalayas.app@evil.example/companies/foo'])
def test_provider_link_cannot_be_replaced_with_untrusted_url(value):
    with pytest.raises(jobs.CollectionError, match='missing_provider'):
        jobs.normalize(sample(applicationLink=value), NOW.isoformat())


@pytest.mark.parametrize('value', [1788732000, 1788732000000, '2026-09-07T00:00:00-05:00'])
def test_timestamp_normalizes_seconds_milliseconds_and_iso(value):
    result = jobs.timestamp(value)
    assert result.endswith('+00:00')
    assert jobs.timestamp(1788732000) == jobs.timestamp(1788732000000)


@pytest.mark.parametrize('value', [True, -1, float('nan'), '2026-09-07', 'nonsense', 1e100])
def test_timestamp_rejects_ambiguous_or_invalid_values(value):
    with pytest.raises(jobs.CollectionError):
        jobs.timestamp(value)


def test_no_assumed_pay_period_or_annualization():
    row = jobs.normalize(sample(salaryPeriod=None), NOW.isoformat())
    assert not any(k.startswith('salary_') for k in row['payload'])
    row = jobs.normalize(sample(minSalary=20, maxSalary=30, salaryPeriod='hourly'), NOW.isoformat())
    assert row['payload']['salary_min'] == 20 and row['payload']['salary_period'] == 'hourly'


def test_description_plain_text_preserves_paragraphs_and_drops_active_content():
    html = '<h2>About &amp; benefits</h2><p>First paragraph.</p><script>alert(1)</script><style>body{display:none}</style><p>Second paragraph.</p><img src="https://example.com/track"><iframe src="https://example.com">hidden</iframe>'
    row = jobs.normalize(sample(description=html), NOW.isoformat())
    assert row['payload']['description'] == 'About & benefits\nFirst paragraph.\nSecond paragraph.'
    assert row['payload']['description_truncated'] is False
    assert row['payload']['normalization_version'] == 2
    assert 'example.com' not in row['payload']['description']


def test_long_description_has_explicit_truncation_marker():
    row = jobs.normalize(sample(description='A' * 25000), NOW.isoformat())
    assert len(row['payload']['description']) == 20000
    assert row['payload']['description_truncated'] is True


def test_optional_description_absence_does_not_reject_job():
    for value in (None, '', {}, '<script>hidden</script>'):
        assert 'description' not in jobs.normalize(sample(description=value), NOW.isoformat())['payload']


def test_description_schema_addition_preserves_original_observations():
    p = jobs.policy(now=NOW)
    old_fields = {k:v for k,v in jobs.FIELDS.items() if k not in ('description', 'description_truncated')}
    dataset = register_dataset({'slug': 'us-jobs-poc', 'title': 'Initial sample', 'fields': old_fields, 'schema_version': 1})
    source = register_source(dataset, {'slug': 'himalayas', 'name': 'Himalayas', 'url': p['attribution_url'], 'attribution':p['attribution'], 'license_url':p['evidence_urls'][0], 'rights_status':'evaluation', 'schema_version':1})
    item = jobs.normalize(sample(description=None), NOW.isoformat())
    item['payload']['normalization_version'] = 1
    ingest_batch(source, [item], 'original-v1')
    new_source = jobs.prepare_source(p)
    assert new_source.schema.version == 2
    assert dataset.schemas.count() == 2
    assert RecordVersion.objects.get().schema.version == 1
    assert RecordVersion.objects.get().payload['normalization_version'] == 1


def test_robots_wildcards_specific_agents_and_allow_ties():
    robots = 'User-agent: *\nAllow: /\nDisallow: /jobs*&page=\nDisallow: /private\nAllow: /private/ok$'
    assert jobs.robots_allowed(robots, jobs.ENDPOINT)[0]
    assert not jobs.robots_allowed(robots, jobs.ENDPOINT + '&page=1')[0]
    assert jobs.robots_allowed(robots, 'https://himalayas.app/private/ok')[0]
    assert not jobs.robots_allowed(robots, 'https://himalayas.app/private/okay')[0]
    assert not jobs.robots_allowed('User-agent: *\nAllow: /\nUser-agent: KWIPJobsPOC\nDisallow: /', jobs.ENDPOINT)[0]
    assert jobs.robots_allowed('User-agent: *\nDisallow: /jobs\nAllow: /jobs', jobs.ENDPOINT)[0]
    assert not jobs.robots_allowed('User-agent: contact\nAllow: /\nUser-agent: *\nDisallow: /jobs', jobs.ENDPOINT)[0]


def test_denied_robots_never_fetches_data_and_preserves_audit():
    fetch = transport(sample(), robots='User-agent: *\nDisallow: /jobs*')
    with pytest.raises(jobs.CollectionError, match='robots_disallowed'):
        jobs.collect(fetch=fetch, now=NOW)
    assert fetch.calls == [jobs.ROBOTS] and not RecordVersion.objects.exists()
    assert CollectionRun.objects.get().summary['data_requests'] == 0


def test_robots_auth_failure_stops_without_bypass():
    calls = []
    def fetch(url, limit):
        calls.append(url)
        return 401, {}, b'Not allowed'
    with pytest.raises(jobs.CollectionError, match='robots_unavailable'):
        jobs.collect(fetch=fetch, now=NOW)
    assert calls == [jobs.ROBOTS]


def test_429_respects_retry_after_and_never_retries_inline():
    fetch = transport(sample(), status=429, headers={'Retry-After': '172800'})
    with pytest.raises(jobs.CollectionError, match='upstream_http_429'):
        jobs.collect(fetch=fetch, now=NOW)
    assert len(fetch.calls) == 2
    assert CollectionState.objects.get().next_allowed_at == NOW + timedelta(days=2)
    assert not RecordVersion.objects.exists()


def test_robots_503_respects_retry_after():
    with pytest.raises(jobs.CollectionError, match='robots_unavailable'):
        jobs.collect(fetch=lambda url, limit: (503, {'Retry-After': '172800'}, b''), now=NOW)
    assert CollectionState.objects.get().next_allowed_at == NOW + timedelta(days=2)


def test_failed_or_empty_next_fetch_never_marks_old_jobs_closed():
    run()
    with pytest.raises(jobs.CollectionError):
        jobs.collect(fetch=transport(status=503), now=NOW + timedelta(days=1))
    assert len(jobs.preview(now=NOW + timedelta(days=1))['records']) == 1
    assert not RecordVersion.objects.filter(tombstone=True).exists()
    jobs.collect(fetch=transport(), now=NOW + timedelta(days=2))
    assert jobs.preview(now=NOW + timedelta(days=2))['records'] == []
    assert RecordVersion.objects.count() == 1


def test_policy_expiry_and_pending_source_never_fetch():
    fetch = transport(sample())
    with pytest.raises(jobs.CollectionError, match='review_due'):
        jobs.collect(fetch=fetch, now=NOW + timedelta(days=7))
    with pytest.raises(jobs.CollectionError, match='not_enabled'):
        jobs.collect('open-jobs', fetch=fetch, now=NOW)
    assert fetch.calls == [] and not Dataset.objects.exists()


def test_expiry_and_source_withdrawal_hide_existing_preview():
    run()
    assert not jobs.preview(now=NOW + timedelta(days=7))['records']
    source = Dataset.objects.get().sources.get()
    source.active = False
    source.save()
    assert not jobs.preview(now=NOW)['records']
    with pytest.raises(jobs.CollectionError, match='disabled'):
        jobs.collect(fetch=transport(sample()), now=NOW + timedelta(days=1))


def test_ingestion_rechecks_revocation_after_network_fetch():
    source = jobs.prepare_source(jobs.policy(now=NOW))
    fetch = transport(sample())
    def revoke(url, limit):
        response = fetch(url, limit)
        if url == jobs.ENDPOINT:
            source.active = False
            source.save()
        return response
    with pytest.raises(jobs.CollectionError, match='ingestion_failed'):
        jobs.collect(fetch=revoke, now=NOW)
    assert not RecordVersion.objects.exists()


def test_retention_removes_only_expired_evaluation_records():
    run()
    assert jobs.purge_expired(now=NOW + timedelta(days=8)) == 1
    assert RecordVersion.objects.count() == Record.objects.count() == 0
    assert CollectionRun.objects.count() == 1
    assert CollectionState.objects.get().last_success_batch_id is None


def test_revocation_and_withdrawal_do_not_cancel_retention():
    run()
    dataset = Dataset.objects.get()
    dataset.sources.update(rights_status='blocked', active=False)
    dataset.status = 'withdrawn'
    dataset.save()
    assert jobs.purge_expired(now=NOW + timedelta(days=8)) == 1
    assert not RecordVersion.objects.exists()


def test_generic_ingestion_of_evaluation_source_requires_draft():
    run()
    source = Dataset.objects.get().sources.get()
    # Simulate an unsupported direct ORM publication to verify service defense.
    Dataset.objects.update(status='published')
    with pytest.raises(ValidationError):
        ingest_batch(source, [jobs.normalize(sample(), NOW.isoformat())], 'new-run')
    assert not Client().get('/api/v2/datasets').json()['datasets']


def test_preview_endpoint_requires_operator_browser_and_costs_nothing():
    run()
    route = '/api/v2/operator/jobs-poc'
    assert Client().get(route).status_code == 401
    identity = Identity.objects.create(subject='user_test_jobs', is_operator=False)
    workspace = Workspace.objects.create(owner=identity)
    client = Client(HTTP_AUTHORIZATION='Bearer fixture', HTTP_ORIGIN='https://kwip.tech')
    with patch('plane.access.auth.verify_session', return_value={'sub': identity.subject}), patch('django.utils.timezone.now', return_value=NOW):
        assert client.get(route).status_code == 403
        identity.is_operator = True
        identity.save()
        response = client.get(route)
        assert response.status_code == 200
        assert response['Cache-Control'] == 'no-store'
        assert response.json()['summary']['records'] == 1
        assert not client.get('/api/v2/plans').json()['purchases_available']
    _, token = issue_key(workspace, 'Operator service', ['ingest:write'], dataset_slugs=['us-jobs-poc'], source_slugs=['himalayas'])
    assert Client(HTTP_AUTHORIZATION='Bearer ' + token).get(route).status_code == 403


def test_plan_is_read_only_and_collection_is_hosted_only():
    with patch('django.utils.timezone.now', return_value=NOW), patch.dict('os.environ', {}, clear=True), patch.object(jobs, 'http_get') as fetch:
        output = StringIO()
        call_command('collect_jobs_poc', stdout=output)
        assert json.loads(output.getvalue())['network_requests'] == 0
        with pytest.raises(CommandError, match='Heroku only'):
            call_command('collect_jobs_poc', collect=True)
    assert not Dataset.objects.exists()
    fetch.assert_not_called()


def test_manifest_cannot_increase_budget_or_enable_customer_access():
    data = copy.deepcopy(jobs.manifest())
    data['sources'][0]['max_data_requests'] = 2
    with patch.object(jobs, 'manifest', return_value=data), pytest.raises(jobs.CollectionError, match='unsupported'):
        jobs.policy(now=NOW)


def test_maximum_twenty_records_from_any_response():
    records = [sample(guid=str(i)) for i in range(40)]
    receipt, _ = run(*records)
    assert receipt['received'] == 40 and receipt['examined'] == receipt['accepted'] == 20
    assert RecordVersion.objects.count() == 20


@pytest.mark.django_db(transaction=True)
def test_concurrent_first_collect_reserves_one_request_budget():
    if connection.vendor != 'postgresql':
        pytest.skip('PostgreSQL row-lock behavior')
    from threading import Barrier
    barrier = Barrier(2)
    fetch = transport(sample())
    def worker():
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            return jobs.collect(fetch=fetch, now=NOW)['status']
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: worker(), range(2)))
    assert sorted(results) == ['complete', 'not_due']
    assert fetch.calls == [jobs.ROBOTS, jobs.ENDPOINT]
    assert CollectionRun.objects.count() == RecordVersion.objects.count() == 1
