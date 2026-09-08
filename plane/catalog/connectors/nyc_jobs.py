"""NYC DCAS external postings; source dates are calendar dates, not UTC instants."""
import math
import re
from datetime import date
from urllib.parse import urlencode

BASE = 'https://data.cityofnewyork.us/resource/kpav-sd4t.json'
ROBOTS = 'https://data.cityofnewyork.us/robots.txt'
ENDPOINT = BASE + '?' + urlencode({'$where': "posting_type='External'", '$order': 'posting_updated DESC,job_id ASC', '$limit': 20})


def calendar_date(value):
    if not value:
        return None
    # Calendar timestamps from Socrata have no timezone. Preserve only stated date.
    value = str(value)
    try:
        return date.fromisoformat(value[:10]).isoformat()
    except ValueError:
        return None


def normalize(job, observed_at):
    from .jobs import CollectionError, description_text, text
    if not isinstance(job, dict):
        raise CollectionError('invalid_job_object')
    if job.get('posting_type') != 'External':
        raise CollectionError('not_external_posting')
    job_id = text(job.get('job_id'), 30)
    if not re.fullmatch(r'\d+', job_id):
        raise CollectionError('invalid_job_id')
    payload = {'title': text(job.get('business_title'), 300), 'company': text(job.get('agency'), 300),
               'country': 'US', 'eligibility': 'us_agency_posting',
               'location_restrictions': 'New York City agency posting; see work location and residency requirements',
               'source_status': 'listed', 'normalization_version': 3}
    for source, field in [('posting_date', 'source_posting_date'), ('posting_updated', 'source_updated_date'), ('process_date', 'source_process_date')]:
        value = calendar_date(job.get(source))
        if value:
            payload[field] = value
    for source, field in [('work_location', 'work_location'), ('post_until', 'source_closing_text'), ('residency_requirement', 'residency_requirement')]:
        if job.get(source):
            clean = description_text(job[source])
            if clean:
                payload[field] = clean[0]
    kind = {'F': 'Full Time', 'P': 'Part Time'}.get(job.get('full_time_part_time_indicator'))
    if kind:
        payload['employment_type'] = kind
    period = {'Annual': 'annual', 'Hourly': 'hourly', 'Daily': 'daily'}.get(job.get('salary_frequency'))
    amounts = {}
    for source, field in [('salary_range_from', 'salary_min'), ('salary_range_to', 'salary_max')]:
        if job.get(source) not in (None, ''):
            try:
                value = float(job[source])
                if isinstance(job[source], bool) or not math.isfinite(value) or not 0 <= value <= 1e12:
                    raise ValueError
            except (ValueError, TypeError):
                raise CollectionError('invalid_salary') from None
            amounts[field] = value
    if amounts.get('salary_min', 0) > amounts.get('salary_max', 1e12):
        raise CollectionError('invalid_salary_range')
    if amounts and period:
        payload.update(amounts, salary_currency='USD', salary_period=period)
    sections = []
    for key, title in [('job_description', 'Description'), ('minimum_qual_requirements', 'Minimum qualifications'), ('preferred_skills', 'Preferred skills'), ('additional_information', 'Additional information'), ('to_apply', 'How to apply'), ('hours_shift', 'Hours and shifts')]:
        if isinstance(job.get(key), str):
            sections.append(title + '\n' + job[key])
    description = description_text('\n'.join(sections))
    if description:
        payload['description'], payload['description_truncated'] = description
    # No invented application URL; point to the exact published source record.
    return {'external_id': job_id, 'payload': payload, 'observed_at': observed_at,
            'source_url': BASE + '?' + urlencode({'job_id': job_id, 'posting_type': 'External'})}


def normalize_response(data, observed_at):
    from .jobs import CollectionError
    if not isinstance(data, list):
        raise CollectionError('unexpected_response_schema')
    items, rejected, seen = [], {}, set()
    for job in data[:20]:
        try:
            row = normalize(job, observed_at)
            if row['external_id'] in seen:
                raise CollectionError('duplicate_source_id')
            seen.add(row['external_id'])
            items.append(row)
        except CollectionError as exc:
            rejected[exc.code] = rejected.get(exc.code, 0) + 1
    return items, {'received': len(data), 'examined': min(20, len(data)), 'accepted': len(items),
                   'rejected': rejected, 'sample_only': True, 'normalization_version': 3}
