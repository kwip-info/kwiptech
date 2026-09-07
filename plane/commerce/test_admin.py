from datetime import timedelta
from decimal import Decimal
import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory
from django.urls import reverse
from django.utils import timezone
from plane.access.models import Identity, Workspace
from .models import BillingAccount, BillingConsent, Delivery, MeterOutbox, MeterReconciliation, StripeEvent

pytestmark = pytest.mark.django_db
MODELS = [BillingAccount, Delivery, MeterOutbox, MeterReconciliation, StripeEvent, BillingConsent]


@pytest.fixture
def diagnostic_rows():
    now = timezone.now()
    identity = Identity.objects.create(subject='user_diagnostics')
    workspace = Workspace.objects.create(owner=identity)
    account = BillingAccount.objects.create(workspace=workspace, checkout_url='https://checkout.example/SECRET_CHECKOUT_TOKEN')
    delivery = Delivery.objects.create(workspace=workspace, dataset_slug='synthetic', request_id='synthetic-request', fingerprint='synthetic', response={'records': ['SECRET_CACHED_RECORD']}, records=1, credits=1, pricing_cents_per_10000=100, period_start=now, period_end=now + timedelta(days=1))
    outbox = MeterOutbox.objects.create(delivery=delivery, customer_id='cus_synthetic', event_name='synthetic', status='review', error_code='deduplication_window')
    reconciliation = MeterReconciliation.objects.create(workspace=workspace, start_at=now, end_at=now + timedelta(hours=1), expected_credits=1, remote_credits=Decimal(0), status='mismatch')
    event = StripeEvent.objects.create(event_id='evt_synthetic', event_type='invoice.paid', payload={'SECRET_WEBHOOK_PAYLOAD': 'must not display'})
    consent = BillingConsent.objects.create(workspace=workspace, identity=identity, overage_enabled=False, spend_cap_cents=0, overage_cents_per_10000=100)
    return [account, delivery, outbox, reconciliation, event, consent]


def client_for(superuser):
    user = get_user_model().objects.create_user(username='super' if superuser else 'staff', is_staff=True, is_superuser=superuser)
    client = Client()
    client.force_login(user)
    return user, client


def route(model, action, obj=None):
    return reverse(f'admin:commerce_{model._meta.model_name}_{action}', args=[obj.pk] if obj else [])


def test_superuser_views_metadata_without_sensitive_payloads(diagnostic_rows):
    _, client = client_for(True)
    for obj in diagnostic_rows:
        response = client.get(route(type(obj), 'change', obj))
        assert response.status_code == 200
        content = response.content.decode()
        for marker in ('SECRET_CACHED_RECORD', 'SECRET_WEBHOOK_PAYLOAD', 'SECRET_CHECKOUT_TOKEN'):
            assert marker not in content
        assert 'name="_save"' not in content
        assert 'deletelink' not in content
        assert client.get(route(type(obj), 'changelist')).status_code == 200


@pytest.mark.parametrize('model', MODELS)
def test_staff_even_with_model_permissions_cannot_view(model, diagnostic_rows):
    from django.contrib.auth.models import Permission
    user, client = client_for(False)
    user.user_permissions.add(*Permission.objects.filter(content_type__app_label='commerce'))
    obj = next(row for row in diagnostic_rows if isinstance(row, model))
    assert client.get(route(model, 'changelist')).status_code == 403
    assert client.get(route(model, 'change', obj)).status_code == 403


@pytest.mark.parametrize('model', MODELS)
def test_superuser_cannot_mutate_or_use_actions(model, diagnostic_rows):
    user, client = client_for(True)
    obj = next(row for row in diagnostic_rows if isinstance(row, model))
    assert client.get(route(model, 'add')).status_code == 403
    assert client.post(route(model, 'change', obj), {'status': 'changed'}).status_code == 403
    assert client.post(route(model, 'delete', obj), {'post': 'yes'}).status_code == 403
    request = RequestFactory().get('/admin/')
    request.user = user
    model_admin = admin.site._registry[model]
    assert model_admin.get_actions(request) == {}
    assert not model_admin.has_add_permission(request)
    assert not model_admin.has_change_permission(request, obj)
    assert not model_admin.has_delete_permission(request, obj)


def test_sensitive_fields_are_excluded_and_deferred(diagnostic_rows):
    user, _ = client_for(True)
    request = RequestFactory().get('/admin/')
    request.user = user
    forbidden = {'response', 'payload', 'checkout_url', 'checkout_generation', 'checkout_session_id'}
    for model in MODELS:
        model_admin = admin.site._registry[model]
        assert not forbidden.intersection(model_admin.get_fields(request))
        assert not forbidden.intersection(model_admin.get_readonly_fields(request))
        assert not forbidden.intersection(model_admin.get_list_display(request))
        assert not forbidden.intersection(model_admin.get_search_fields(request))
        row = model_admin.get_queryset(request).first()
        assert set(model_admin.sensitive_fields) <= row.get_deferred_fields()


def test_search_and_status_filters_are_usable(diagnostic_rows):
    _, client = client_for(True)
    delivery = diagnostic_rows[1]
    assert client.get(route(Delivery, 'changelist'), {'q': str(delivery.workspace_id)}).status_code == 200
    assert client.get(route(MeterOutbox, 'changelist'), {'status__exact': 'review'}).status_code == 200
    assert client.get(route(StripeEvent, 'changelist'), {'q': 'evt_synthetic'}).status_code == 200


def test_anonymous_is_redirected_and_inactive_superuser_has_no_permission():
    for model in MODELS:
        assert Client().get(route(model, 'changelist')).status_code == 302
        user = get_user_model()(is_staff=True, is_superuser=True, is_active=False)
        request = RequestFactory().get('/admin/')
        request.user = user
        model_admin = admin.site._registry[model]
        assert not model_admin.has_view_permission(request)
        assert not model_admin.has_module_permission(request)
