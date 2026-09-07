import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from io import StringIO
import json

from .models import Dataset, Record, RecordVersion, SchemaVersion, IngestionBatch
from .services import register_dataset, register_source, ingest_batch, read_records, validate_schema

pytestmark = pytest.mark.django_db


def manifest():
    return {'slug': 'synthetic', 'title': 'Synthetic', 'schema_version': 1, 'fields': {'name': {'type': 'string', 'required': True}, 'count': {'type': 'integer'}, 'active': {'type': 'boolean'}}}


@pytest.fixture
def catalog():
    dataset = register_dataset(manifest())
    source = register_source(dataset, {'slug': 'synthetic', 'name': 'Synthetic', 'url': 'https://example.com/data', 'schema_version': 1, 'rights_status': 'approved', 'license_url': 'https://example.com/license', 'attribution': 'Synthetic tests'})
    dataset.status = 'published'
    dataset.full_clean()
    dataset.save()
    return dataset, source


def item(key='a', name='First', **kwargs):
    return {'external_id': key, 'payload': {'name': name, 'count': 1, 'active': True}, 'observed_at': '2026-01-01T00:00:00Z', **kwargs}


def test_registration_dry_run_and_replay():
    register_dataset(manifest(), dry_run=True)
    assert not Dataset.objects.exists()
    dataset = register_dataset(manifest())
    assert register_dataset(manifest()).pk == dataset.pk
    assert SchemaVersion.objects.count() == 1
    changed = manifest()
    changed['fields']['other'] = {'type': 'string'}
    with pytest.raises(ValidationError):
        register_dataset(changed)


@pytest.mark.parametrize('fields', [{}, {'bad__key': {'type': 'string'}}, {'x': {'type': 'sql'}}, {'x': {'type': 'enum'}}, {'x': {'type': 'string', 'required': 'yes'}}, []])
def test_malformed_schema(fields):
    with pytest.raises(ValidationError):
        validate_schema(fields)


def test_publication_requires_rights():
    data = manifest()
    data['status'] = 'published'
    with pytest.raises(ValidationError):
        register_dataset(data)


def test_ingestion_atomic_and_idempotent(catalog):
    dataset, source = catalog
    with pytest.raises(ValidationError):
        ingest_batch(source, [item(), item('b', payload={'count': 2})], 'bad')
    assert not Record.objects.exists()
    assert not IngestionBatch.objects.exists()
    assert ingest_batch(source, [item()], 'dry', dry_run=True)['validated'] == 1
    assert not Record.objects.exists()
    result = ingest_batch(source, [item()], 'one')
    assert result['versions_created'] == 1
    assert ingest_batch(source, [item()], 'one')['replayed']
    assert RecordVersion.objects.count() == 1
    with pytest.raises(ValidationError):
        ingest_batch(source, [item(name='Changed')], 'one')


@pytest.mark.parametrize('bad', [item(observed_at='2026-01-01T00:00:00'), item(payload={'name': 'x', 'count': True}), item(payload={'name': 'x', 'active': 'yes'}), item(payload={'name': 'x', 'unknown': 'x'}), item(tombstone='yes'), item(tombstone=True), item(source_url='file:///tmp/a')])
def test_invalid_item(catalog, bad):
    with pytest.raises(ValidationError):
        ingest_batch(catalog[1], [bad], 'bad')
    assert not Record.objects.exists()


def test_duplicate_and_bounds(catalog):
    for items in ([], [item(), item()], [item(str(i)) for i in range(501)]):
        with pytest.raises(ValidationError):
            ingest_batch(catalog[1], items, 'bad')


def test_versions_equal_observation_and_tombstone(catalog):
    dataset, source = catalog
    ingest_batch(source, [item()], 'one')
    ingest_batch(source, [item()], 'two')
    assert Record.objects.count() == 1
    assert RecordVersion.objects.count() == 2
    assert len(set(RecordVersion.objects.values_list('content_hash', flat=True))) == 1
    ingest_batch(source, [item(payload={}, tombstone=True)], 'delete')
    assert read_records(dataset)['records'] == []
    ingest_batch(source, [item(name='Restored')], 'restore')
    assert read_records(dataset)['records'][0]['data']['name'] == 'Restored'


def test_snapshot_and_projection_filters(catalog):
    dataset, source = catalog
    ingest_batch(source, [item('a'), item('b'), item('c')], 'first')
    first = read_records(dataset, limit=1, fields=['name'], filters={'count': 1})
    ingest_batch(source, [item('b', name='Changed'), item('d')], 'second')
    second = read_records(dataset, limit=1, cursor=first['next_cursor'], fields=['name'], filters={'count': 1})
    assert second['snapshot'] == first['snapshot']
    assert second['records'][0]['data'] == {'name': 'First'}
    third = read_records(dataset, limit=1, cursor=second['next_cursor'], fields=['name'], filters={'count': 1})
    assert third['records'][0]['external_id'] == 'c'
    assert third['next_cursor'] is None
    with pytest.raises(ValidationError):
        read_records(dataset, cursor=first['next_cursor'])
    with pytest.raises(ValidationError):
        read_records(dataset, cursor='tampered')


def test_rights_revocation_and_drafts(catalog):
    dataset, source = catalog
    ingest_batch(source, [item()], 'first')
    source.rights_status = 'blocked'
    source.save()
    assert read_records(dataset)['count'] == 0
    with pytest.raises(ValidationError):
        ingest_batch(source, [item()], 'second')
    dataset.status = 'draft'
    dataset.save()
    with pytest.raises(ValidationError):
        read_records(dataset)


@pytest.mark.parametrize('kwargs', [{'limit': 101}, {'limit': True}, {'filters': {'name__contains': 'a'}}, {'filters': {'count': '1'}}, {'fields': ['missing']}, {'fields': 'name'}])
def test_query_rejects_unsafe_inputs(catalog, kwargs):
    with pytest.raises(ValidationError):
        read_records(catalog[0], **kwargs)


def test_cli_registration_dry_run(tmp_path):
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps(manifest()))
    output = StringIO()
    call_command('register_dataset', str(path), dry_run=True, stdout=output)
    assert json.loads(output.getvalue())['dry_run']
    assert not Dataset.objects.exists()


def test_schema_and_source_provenance_immutable(catalog):
    dataset, source = catalog
    ingest_batch(source, [item()], 'first')
    schema = dataset.schemas.get(version=1)
    schema.fields = {'different': {'type': 'string'}}
    with pytest.raises(ValidationError):
        schema.save()
    source.attribution = 'Changed later'
    source.save()
    assert read_records(dataset)['records'][0]['source']['attribution'] == 'Synthetic tests'


def test_source_registration_dry_run_and_cross_dataset(catalog):
    dataset, source = catalog
    result = register_source(dataset, {'slug': source.slug, 'name': 'Changed', 'url': source.url, 'schema_version': 1}, dry_run=True)
    assert result.name == 'Changed'
    source.refresh_from_db()
    assert source.name == 'Synthetic'
    other = manifest()
    other['slug'] = 'other'
    other_dataset = register_dataset(other)
    source.schema = other_dataset.schemas.get()
    with pytest.raises(ValidationError):
        source.full_clean()


def test_cli_ingestion_dry_run(catalog, tmp_path):
    path = tmp_path / 'batch.json'
    path.write_text(json.dumps([item()]))
    output = StringIO()
    call_command('ingest_dataset', 'synthetic', 'synthetic', str(path), idempotency_key='cli', dry_run=True, stdout=output)
    assert json.loads(output.getvalue())['validated'] == 1
    assert not Record.objects.exists()


@pytest.mark.parametrize('value', [[], {}, ['string'], 123, None])
def test_invalid_schema_type_returns_validation(value):
    with pytest.raises(ValidationError):
        validate_schema({'name': {'type': value}})


@pytest.mark.parametrize('key,value', [('slug', {}), ('title', []), ('status', {}), ('schema_version', 10**100), ('credits_per_record', 10**100)])
def test_malformed_manifest_scalars(key, value):
    data = manifest()
    data[key] = value
    with pytest.raises(ValidationError):
        register_dataset(data)


def test_extreme_input(catalog):
    nested = []
    for _ in range(1500):
        nested = [nested]
    for payload in ({'name': nested}, {'name': 'x' * 100_001}, {'name': 'x', 'count': 10**10000}):
        with pytest.raises(ValidationError):
            ingest_batch(catalog[1], [item(payload=payload)], 'invalid')


def test_compatible_schema_evolution_pins_cursor(catalog):
    dataset, source = catalog
    ingest_batch(source, [item('a'), item('b')], 'first')
    first = read_records(dataset, limit=1)
    changed = manifest()
    changed['schema_version'] = 2
    changed['fields']['new'] = {'type': 'string'}
    register_dataset(changed)
    assert read_records(dataset, cursor=first['next_cursor'])['count'] == 1
    changed['schema_version'] = 3
    changed['fields']['count'] = {'type': 'string'}
    with pytest.raises(ValidationError):
        register_dataset(changed)
    changed['fields'].pop('count')
    with pytest.raises(ValidationError):
        register_dataset(changed)


def test_source_identity_cannot_move(catalog):
    _, source = catalog
    source.slug = 'moved'
    with pytest.raises(ValidationError):
        source.full_clean()


@pytest.mark.parametrize('cursor', [[], {}, 123, 'x' * 8193])
def test_cursor_malformed_types(catalog, cursor):
    with pytest.raises(ValidationError):
        read_records(catalog[0], cursor=cursor)


def test_admin_rights_gate_and_immutable_history(catalog):
    from django.contrib.admin.sites import AdminSite
    from django.test import RequestFactory
    from .admin import DatasetAdmin, ImmutableAdmin, SourceAdmin
    from .models import Source
    request = RequestFactory().get('/')
    dataset, source = catalog
    form_class = SourceAdmin(Source, AdminSite()).get_form(request, obj=source)
    data = {'dataset': dataset.pk, 'slug': source.slug, 'name': source.name, 'url': source.url, 'rights_status': 'approved', 'active': True, 'schema': source.schema_id, 'license_url': '', 'attribution': ''}
    form = form_class(data=data, instance=source)
    assert not form.is_valid()
    assert 'Approved rights' in str(form.errors)
    immutable = ImmutableAdmin(RecordVersion, AdminSite())
    assert not immutable.has_add_permission(request)
    assert not immutable.has_change_permission(request)
    assert not immutable.has_delete_permission(request)
    draft = register_dataset({**manifest(), 'slug': 'draft'})
    form_class = DatasetAdmin(Dataset, AdminSite()).get_form(request, obj=draft)
    form = form_class(data={'slug': draft.slug, 'title': draft.title, 'status': 'published', 'credits_per_record': 1}, instance=draft)
    assert not form.is_valid()
    assert 'Publication requires' in str(form.errors)
