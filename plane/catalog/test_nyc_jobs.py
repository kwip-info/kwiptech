"""Invented fixtures only; no live dataset traffic from tests."""
import json
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.test import Client

from plane.catalog.connectors import jobs, nyc_jobs
from plane.catalog.models import Dataset, RecordVersion, CollectionState
from plane.catalog.test_jobs_poc import NOW, run

pytestmark = pytest.mark.django_db


def sample(**changes):
    return dict(job_id='123456', posting_type='External', business_title='Example engineer',
                agency='Invented City Agency', work_location='Example office',
                full_time_part_time_indicator='F', salary_range_from='90000.00', salary_range_to='110000',
                salary_frequency='Annual', posting_date='2026-09-01T00:00:00.000',
                posting_updated='2026-09-08T00:00:00.000', post_until='Until filled',
                job_description='<p>Invented role</p><script>evil()</script>',
                minimum_qual_requirements='Example qualification', residency_requirement='See agency rules',
                recruitment_contact='excluded@example.test') | changes


def transport(*rows, robots='User-agent: *\nAllow: /', status=200):
    calls = []
    def fetch(url, limit):
        calls.append(url)
        if url == nyc_jobs.ROBOTS:
            return 200, {}, robots.encode()
        return status, {}, json.dumps(list(rows or [sample()])).encode()
    fetch.calls = calls
    return fetch


def test_dates_unknown_remote_pay_and_safe_description():
    row = nyc_jobs.normalize(sample(), NOW.isoformat())
    d = row['payload']
    assert d['source_posting_date'] == '2026-09-01'
    assert 'published_at' not in d and 'effective_at' not in row and 'remote' not in d
    assert d['source_closing_text'] == 'Until filled'
    assert d['salary_min'] == 90000 and d['salary_period'] == 'annual'
    assert 'Minimum qualifications' in d['description'] and 'evil' not in d['description']
    assert 'recruitment_contact' not in d
    assert row['source_url'].endswith('job_id=123456&posting_type=External')


@pytest.mark.parametrize('changes,error', [({'posting_type':'Internal'},'not_external'), ({'job_id':'../evil'},'invalid_job_id'), ({'salary_range_from':'NaN'},'invalid_salary'), ({'salary_range_from':'120000'},'invalid_salary_range')])
def test_bad_rows_rejected(changes,error):
    with pytest.raises(jobs.CollectionError, match=error):
        nyc_jobs.normalize(sample(**changes), NOW.isoformat())


def test_daily_pay_and_invalid_optional_dates():
    row = nyc_jobs.normalize(sample(salary_frequency='Daily', posting_date='not-date'), NOW.isoformat())['payload']
    assert row['salary_period'] == 'daily' and 'source_posting_date' not in row


def test_multi_source_independent_budgets_schema_versions_and_private_preview():
    run()
    fetch = transport()
    with patch('django.utils.timezone.now', return_value=NOW):
        receipt = jobs.collect('nyc-dcas', fetch=fetch, now=NOW)
    assert receipt['accepted'] == 1
    assert fetch.calls == [nyc_jobs.ROBOTS, nyc_jobs.ENDPOINT]
    assert jobs.collect('nyc-dcas', fetch=fetch, now=NOW)['status'] == 'not_due'
    assert len(fetch.calls) == 2 and CollectionState.objects.count() == 2
    assert set(RecordVersion.objects.values_list('schema__version',flat=True)) == {2,3}
    view = jobs.preview(now=NOW)
    assert len(view['records']) == 2 and len(view['collection_status']) == 2
    assert {r['source_id'] for r in view['records']} == {'himalayas','nyc-dcas'}
    assert Client().get('/api/v2/datasets').json()['datasets'] == []
    source = Dataset.objects.get().sources.get(slug='nyc-dcas')
    source.active = False
    source.save()
    assert [r['source_id'] for r in jobs.preview(now=NOW)['records']] == ['himalayas']


def test_new_source_robots_and_failure_do_not_hide_other_sample():
    run()
    fetch = transport(robots='User-agent: *\nDisallow: /resource/')
    with pytest.raises(jobs.CollectionError, match='robots_disallowed'):
        jobs.collect('nyc-dcas', fetch=fetch, now=NOW)
    assert fetch.calls == [nyc_jobs.ROBOTS]
    assert len(jobs.preview(now=NOW)['records']) == 1


def test_expired_policy_only_hides_affected_source():
    run()
    later=NOW+timedelta(days=1)
    with patch('django.utils.timezone.now',return_value=later):
        jobs.collect('nyc-dcas',fetch=transport(),now=later)
    assert [r['source_id'] for r in jobs.preview(now=NOW+timedelta(days=7))['records']] == ['nyc-dcas']


def test_response_bound_and_duplicates():
    items, summary = nyc_jobs.normalize_response([sample(),sample(),sample(posting_type='Internal')],NOW.isoformat())
    assert len(items)==1 and summary['rejected']=={'duplicate_source_id':1,'not_external_posting':1}
    assert len(nyc_jobs.normalize_response([sample(job_id=str(i)) for i in range(30)],NOW.isoformat())[0]) == 20
