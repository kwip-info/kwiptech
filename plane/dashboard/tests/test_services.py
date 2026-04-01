"""Tests for dashboard service layer."""

from django.test import TestCase

from plane.core.defaults import seed_default_roles, seed_permissions
from plane.core.models import (
    Account,
    ApiKey,
    Application,
    Membership,
    Organization,
    Permission,
    Role,
    RolePermission,
    SyncBatchRecord,
)
from plane.dashboard.services import (
    create_api_key,
    get_key_summary,
    get_keys,
    get_onboarding_status,
    get_sync_status,
    get_usage_summary,
    revoke_api_key,
)


def _make_account(**kwargs):
    defaults = {"id": "test_acc", "email": "test@test.com"}
    defaults.update(kwargs)
    return Account.objects.create(**defaults)


def _make_org_and_app(account):
    """Create an org with default roles and a default app."""
    seed_permissions(Permission)
    org = Organization.objects.create(
        id=f"org_{account.id}", name="Test Org", slug=f"test-{account.id}",
        owner=account, is_personal=True,
    )
    seed_default_roles(org, Role, RolePermission, Permission)
    owner_role = org.roles.get(name="Owner")
    Membership.objects.create(
        id=f"mem_{account.id}", organization=org, account=account, role=owner_role,
    )
    app = Application.objects.create(
        id=f"app_{account.id}", organization=org, name="Default",
        slug="default", is_default=True,
    )
    return org, app


class TestGetKeySummary(TestCase):

    def test_counts_active_and_revoked(self):
        account = _make_account()
        org, app = _make_org_and_app(account)
        create_api_key(account, app, "test", "key1")
        key2, _ = create_api_key(account, app, "test", "key2")
        revoke_api_key(app, key2.id)

        summary = get_key_summary(app, "test")
        assert summary["active"] == 1
        assert summary["revoked"] == 1
        assert summary["total"] == 2

    def test_filters_by_environment(self):
        account = _make_account()
        org, app = _make_org_and_app(account)
        create_api_key(account, app, "test")
        create_api_key(account, app, "live")

        assert get_key_summary(app, "test")["active"] == 1
        assert get_key_summary(app, "live")["active"] == 1


class TestCreateApiKey(TestCase):

    def test_returns_key_and_full_key(self):
        account = _make_account()
        org, app = _make_org_and_app(account)
        api_key, full_key = create_api_key(account, app, "test", "my label")

        assert api_key.account == account
        assert api_key.application == app
        assert api_key.environment == "test"
        assert api_key.label == "my label"
        assert api_key.is_active is True
        assert full_key.startswith("psc_test_")

    def test_full_key_not_stored(self):
        account = _make_account()
        org, app = _make_org_and_app(account)
        api_key, full_key = create_api_key(account, app, "live")

        refreshed = ApiKey.objects.get(id=api_key.id)
        assert refreshed.key_hash != full_key
        assert refreshed.key_prefix == full_key[:13]


class TestRevokeApiKey(TestCase):

    def test_marks_key_inactive(self):
        account = _make_account()
        org, app = _make_org_and_app(account)
        api_key, _ = create_api_key(account, app, "test")

        revoked = revoke_api_key(app, api_key.id)
        assert revoked.is_active is False
        assert revoked.revoked_at is not None

    def test_cannot_revoke_other_apps_key(self):
        account1 = _make_account(id="acc1", email="a1@test.com")
        account2 = _make_account(id="acc2", email="a2@test.com")
        org1, app1 = _make_org_and_app(account1)
        org2, app2 = _make_org_and_app(account2)
        api_key, _ = create_api_key(account1, app1, "test")

        with self.assertRaises(ApiKey.DoesNotExist):
            revoke_api_key(app2, api_key.id)


class TestGetSyncStatus(TestCase):

    def test_returns_none_when_no_syncs(self):
        account = _make_account()
        org, app = _make_org_and_app(account)
        assert get_sync_status(org) is None

    def test_returns_latest_batch_info(self):
        account = _make_account()
        org, app = _make_org_and_app(account)
        SyncBatchRecord.objects.create(
            id="batch1", account=account,
            first_sequence=1, last_sequence=10,
            chain_hash="abc", content_hash="def",
            signature="sig", entry_count=10, sdk_version="0.4.0",
        )
        status = get_sync_status(org)
        assert status is not None
        assert status["last_batch_count"] == 10


class TestGetOnboardingStatus(TestCase):

    def test_new_org_not_complete(self):
        account = _make_account()
        org, app = _make_org_and_app(account)
        status = get_onboarding_status(org)
        assert status["has_key"] is False
        assert status["has_synced"] is False
        assert status["is_complete"] is False

    def test_detects_key_creation(self):
        account = _make_account()
        org, app = _make_org_and_app(account)
        create_api_key(account, app, "test")
        status = get_onboarding_status(org)
        assert status["has_key"] is True

    def test_key_detection_is_sticky(self):
        account = _make_account()
        org, app = _make_org_and_app(account)
        api_key, _ = create_api_key(account, app, "test")
        revoke_api_key(app, api_key.id)
        status = get_onboarding_status(org)
        assert status["has_key"] is True
