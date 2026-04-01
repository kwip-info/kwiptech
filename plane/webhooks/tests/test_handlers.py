"""Tests for Clerk webhook event handlers."""

from django.test import TestCase

from plane.core.defaults import seed_permissions
from plane.core.models import (
    Account,
    Application,
    Membership,
    Organization,
    Permission,
    Role,
    RolePermission,
)
from plane.webhooks.handlers import (
    handle_membership_created,
    handle_membership_deleted,
    handle_membership_updated,
    handle_organization_created,
    handle_organization_deleted,
    handle_organization_updated,
)


class OrganizationCreatedTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        seed_permissions(Permission)
        cls.creator = Account.objects.create(
            id="acc_creator", clerk_user_id="user_creator",
        )

    def test_creates_organization(self):
        handle_organization_created({
            "id": "org_clerk_1",
            "name": "Acme Corp",
            "slug": "acme-corp",
            "created_by": "user_creator",
        })
        org = Organization.objects.get(clerk_org_id="org_clerk_1")
        assert org.name == "Acme Corp"
        assert org.slug == "acme-corp"
        assert org.owner == self.creator

    def test_creates_default_roles(self):
        handle_organization_created({
            "id": "org_roles_test",
            "name": "Roles Test",
            "slug": "roles-test",
            "created_by": "user_creator",
        })
        org = Organization.objects.get(clerk_org_id="org_roles_test")
        role_names = set(org.roles.values_list("name", flat=True))
        assert role_names == {"Owner", "Admin", "Developer", "Viewer"}

    def test_creates_default_application(self):
        handle_organization_created({
            "id": "org_app_test",
            "name": "App Test",
            "slug": "app-test",
            "created_by": "user_creator",
        })
        org = Organization.objects.get(clerk_org_id="org_app_test")
        app = org.applications.get(is_default=True)
        assert app.name == "Default"
        assert app.slug == "default"

    def test_idempotent(self):
        data = {
            "id": "org_idem",
            "name": "Idem Corp",
            "slug": "idem-corp",
            "created_by": "user_creator",
        }
        handle_organization_created(data)
        handle_organization_created(data)
        assert Organization.objects.filter(clerk_org_id="org_idem").count() == 1

    def test_creates_account_if_creator_not_found(self):
        handle_organization_created({
            "id": "org_new_user",
            "name": "New User Org",
            "slug": "new-user-org",
            "created_by": "user_unknown_creator",
        })
        assert Account.objects.filter(clerk_user_id="user_unknown_creator").exists()

    def test_owner_role_has_all_permissions(self):
        handle_organization_created({
            "id": "org_perm_test",
            "name": "Perm Test",
            "slug": "perm-test",
            "created_by": "user_creator",
        })
        org = Organization.objects.get(clerk_org_id="org_perm_test")
        owner_role = org.roles.get(name="Owner")
        perm_count = owner_role.permissions.count()
        assert perm_count == 14


class OrganizationUpdatedTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        seed_permissions(Permission)
        cls.owner = Account.objects.create(id="acc_upd", clerk_user_id="user_upd")
        cls.org = Organization.objects.create(
            id="org_upd", name="Old Name", slug="old-name",
            clerk_org_id="org_clerk_upd", owner=cls.owner,
        )

    def test_updates_name(self):
        handle_organization_updated({"id": "org_clerk_upd", "name": "New Name"})
        self.org.refresh_from_db()
        assert self.org.name == "New Name"


class OrganizationDeletedTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        seed_permissions(Permission)
        cls.owner = Account.objects.create(id="acc_del", clerk_user_id="user_del")

    def test_archives_organization(self):
        org = Organization.objects.create(
            id="org_del", name="Del Org", slug="del-org",
            clerk_org_id="org_clerk_del", owner=self.owner,
        )
        handle_organization_deleted({"id": "org_clerk_del"})
        org.refresh_from_db()
        assert org.status == "archived"


class MembershipFirstMemberTest(TestCase):
    """Test that the first member of an org gets the Owner role."""

    @classmethod
    def setUpTestData(cls):
        seed_permissions(Permission)
        cls.owner = Account.objects.create(id="acc_first", clerk_user_id="user_first")
        cls.org = Organization.objects.create(
            id="org_first", name="First Org", slug="first-org",
            clerk_org_id="org_clerk_first", owner=cls.owner,
        )
        from plane.core.defaults import seed_default_roles
        seed_default_roles(cls.org, Role, RolePermission, Permission)

    def test_first_member_gets_owner_role(self):
        handle_membership_created({
            "id": "mem_clerk_first",
            "organization": {"id": "org_clerk_first"},
            "public_user_data": {"user_id": "user_first"},
            "role": "org:admin",
        })
        mem = Membership.objects.get(organization=self.org, account=self.owner)
        assert mem.role.name == "Owner"


class MembershipCreatedTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        seed_permissions(Permission)
        cls.owner = Account.objects.create(id="acc_mem", clerk_user_id="user_mem")
        cls.org = Organization.objects.create(
            id="org_mem", name="Mem Org", slug="mem-org",
            clerk_org_id="org_clerk_mem", owner=cls.owner,
        )
        from plane.core.defaults import seed_default_roles
        seed_default_roles(cls.org, Role, RolePermission, Permission)
        owner_role = cls.org.roles.get(name="Owner")
        Membership.objects.create(
            id="mem_owner", organization=cls.org, account=cls.owner, role=owner_role,
        )

    def test_creates_membership_with_developer_role(self):
        member = Account.objects.create(id="acc_new_mem", clerk_user_id="user_new_mem")
        handle_membership_created({
            "id": "mem_clerk_1",
            "organization": {"id": "org_clerk_mem"},
            "public_user_data": {"user_id": "user_new_mem"},
            "role": "org:member",
        })
        mem = Membership.objects.get(organization=self.org, account=member)
        assert mem.role.name == "Developer"
        assert mem.clerk_membership_id == "mem_clerk_1"

    def test_admin_role_mapped_correctly(self):
        admin = Account.objects.create(id="acc_admin_mem", clerk_user_id="user_admin_mem")
        handle_membership_created({
            "id": "mem_clerk_admin",
            "organization": {"id": "org_clerk_mem"},
            "public_user_data": {"user_id": "user_admin_mem"},
            "role": "org:admin",
        })
        mem = Membership.objects.get(organization=self.org, account=admin)
        assert mem.role.name == "Admin"

    def test_idempotent(self):
        Account.objects.create(id="acc_idem_mem", clerk_user_id="user_idem_mem")
        data = {
            "id": "mem_clerk_idem",
            "organization": {"id": "org_clerk_mem"},
            "public_user_data": {"user_id": "user_idem_mem"},
            "role": "org:member",
        }
        handle_membership_created(data)
        handle_membership_created(data)
        assert Membership.objects.filter(
            organization=self.org, account__clerk_user_id="user_idem_mem",
        ).count() == 1

    def test_creates_account_if_not_found(self):
        handle_membership_created({
            "id": "mem_clerk_new_acc",
            "organization": {"id": "org_clerk_mem"},
            "public_user_data": {"user_id": "user_brand_new"},
            "role": "org:member",
        })
        assert Account.objects.filter(clerk_user_id="user_brand_new").exists()


class MembershipUpdatedTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        seed_permissions(Permission)
        cls.owner = Account.objects.create(id="acc_mu", clerk_user_id="user_mu")
        cls.org = Organization.objects.create(
            id="org_mu", name="MU Org", slug="mu-org",
            clerk_org_id="org_clerk_mu", owner=cls.owner,
        )
        from plane.core.defaults import seed_default_roles
        seed_default_roles(cls.org, Role, RolePermission, Permission)
        dev_role = cls.org.roles.get(name="Developer")
        cls.membership = Membership.objects.create(
            id="mem_mu", organization=cls.org, account=cls.owner,
            role=dev_role, clerk_membership_id="mem_clerk_mu",
        )

    def test_updates_role(self):
        handle_membership_updated({
            "id": "mem_clerk_mu",
            "role": "org:admin",
        })
        self.membership.refresh_from_db()
        assert self.membership.role.name == "Admin"


class MembershipDeletedTest(TestCase):

    def test_deletes_membership(self):
        owner = Account.objects.create(id="acc_md", clerk_user_id="user_md")
        org = Organization.objects.create(
            id="org_md", name="MD Org", slug="md-org", owner=owner,
        )
        role = Role.objects.create(id="role_md", organization=org, name="Dev")
        Membership.objects.create(
            id="mem_md", organization=org, account=owner,
            role=role, clerk_membership_id="mem_clerk_md",
        )
        handle_membership_deleted({"id": "mem_clerk_md"})
        assert not Membership.objects.filter(clerk_membership_id="mem_clerk_md").exists()
