"""Tests for account lookup/creation from Clerk claims."""

from django.test import TestCase

from plane.auth.services import ensure_personal_organization, get_or_create_account
from plane.core.defaults import seed_permissions
from plane.core.models import Account, Membership, Organization, Permission


class TestGetOrCreateAccount(TestCase):

    def test_returns_existing_account_by_clerk_user_id(self):
        account = Account.objects.create(
            id="acc_existing", email="existing@test.com", clerk_user_id="user_clerk_1",
        )
        result = get_or_create_account("user_clerk_1", {"email": "existing@test.com"})
        assert result.id == account.id

    def test_links_existing_account_by_email(self):
        account = Account.objects.create(
            id="acc_api", email="api@test.com",
        )
        assert account.clerk_user_id is None

        result = get_or_create_account("user_new_clerk", {"email": "api@test.com"})

        assert result.id == account.id
        account.refresh_from_db()
        assert account.clerk_user_id == "user_new_clerk"

    def test_creates_new_account(self):
        result = get_or_create_account("user_brand_new", {"email": "brand_new@test.com"})

        assert result.clerk_user_id == "user_brand_new"
        assert result.email == "brand_new@test.com"
        assert Account.objects.filter(clerk_user_id="user_brand_new").exists()

    def test_missing_email_creates_account_without_email(self):
        result = get_or_create_account("user_no_email", {})
        assert result.clerk_user_id == "user_no_email"
        assert result.email is None

    def test_new_account_has_active_status(self):
        result = get_or_create_account("user_status", {"email": "status@test.com"})
        assert result.status == "active"


class TestEnsurePersonalOrganization(TestCase):

    @classmethod
    def setUpTestData(cls):
        seed_permissions(Permission)

    def test_creates_personal_org(self):
        account = Account.objects.create(
            id="acc_pers", email="pers@test.com", clerk_user_id="user_pers",
        )
        org = ensure_personal_organization(account)
        assert org.is_personal is True
        assert org.owner == account
        assert org.plan == "free"

    def test_creates_default_app(self):
        account = Account.objects.create(
            id="acc_app", email="app@test.com", clerk_user_id="user_app",
        )
        org = ensure_personal_organization(account)
        app = org.applications.get(is_default=True)
        assert app.name == "Default"

    def test_creates_owner_membership(self):
        account = Account.objects.create(
            id="acc_mem", email="mem@test.com", clerk_user_id="user_mem",
        )
        org = ensure_personal_organization(account)
        mem = Membership.objects.get(organization=org, account=account)
        assert mem.role.name == "Owner"

    def test_creates_four_default_roles(self):
        account = Account.objects.create(
            id="acc_roles", email="roles@test.com", clerk_user_id="user_roles",
        )
        org = ensure_personal_organization(account)
        role_names = set(org.roles.values_list("name", flat=True))
        assert role_names == {"Owner", "Admin", "Developer", "Viewer"}

    def test_idempotent(self):
        account = Account.objects.create(
            id="acc_idem", email="idem@test.com", clerk_user_id="user_idem",
        )
        org1 = ensure_personal_organization(account)
        org2 = ensure_personal_organization(account)
        assert org1.id == org2.id
        assert Organization.objects.filter(owner=account, is_personal=True).count() == 1

    def test_new_account_gets_personal_org(self):
        account = get_or_create_account("user_auto_org", {"email": "auto@test.com"})
        org = account.personal_organization
        assert org is not None
        assert org.is_personal is True
