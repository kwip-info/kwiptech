import io
import json
import pytest
from django.core.management import call_command, CommandError
from plane.catalog.models import Dataset

pytestmark = pytest.mark.django_db


def test_empty_gate_is_read_only_and_rejects_any_catalog_entry():
    out = io.StringIO()
    call_command('marketplace_preflight', require_empty=True, stdout=out)
    assert json.loads(out.getvalue())['ok']
    Dataset.objects.create(slug='private-draft', title='Draft')
    out = io.StringIO()
    with pytest.raises(CommandError):
        call_command('marketplace_preflight', require_empty=True, stdout=out)
    report = json.loads(out.getvalue())
    assert report['counts']['catalog.dataset'] == 1
    assert Dataset.objects.count() == 1
    assert 'private-draft' not in out.getvalue()
