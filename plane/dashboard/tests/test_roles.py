"""Tests for role management pages."""

from django.test import TestCase

from plane.core.models import Account, Application, Organization, Permission, Role


class RolesPageTest(TestCase):

    def setUp(self):
        self.client.get("/dashboard/")
        self.account = Account.objects.get(id="test_account")
        self.org = Organization.objects.get(id="test_org")

    def test_returns_200(self):
        response = self.client.get("/dashboard/roles/")
        assert response.status_code == 200

    def test_uses_correct_template(self):
        response = self.client.get("/dashboard/roles/")
        self.assertTemplateUsed(response, "dashboard/roles.html")

    def test_shows_default_roles(self):
        response = self.client.get("/dashboard/roles/")
        self.assertContains(response, "Owner")
        self.assertContains(response, "Admin")
        self.assertContains(response, "Developer")
        self.assertContains(response, "Viewer")

    def test_shows_system_badge(self):
        response = self.client.get("/dashboard/roles/")
        self.assertContains(response, "System")

    def test_shows_new_role_button(self):
        response = self.client.get("/dashboard/roles/")
        self.assertContains(response, "New Role")


class RoleEditorTest(TestCase):

    def setUp(self):
        self.client.get("/dashboard/")
        self.account = Account.objects.get(id="test_account")
        self.org = Organization.objects.get(id="test_org")

    def test_new_role_page_returns_200(self):
        response = self.client.get("/dashboard/roles/new/")
        assert response.status_code == 200

    def test_new_role_shows_permissions(self):
        response = self.client.get("/dashboard/roles/new/")
        self.assertContains(response, "View API keys")
        self.assertContains(response, "Create API keys")

    def test_create_role_via_post(self):
        response = self.client.post("/dashboard/roles/new/", {
            "name": "Billing Manager",
            "permissions": ["billing.view", "billing.manage"],
        })
        assert response.status_code == 302
        role = Role.objects.get(organization=self.org, name="Billing Manager")
        perm_ids = set(role.permissions.values_list("id", flat=True))
        assert perm_ids == {"billing.view", "billing.manage"}

    def test_create_role_without_name_shows_error(self):
        response = self.client.post("/dashboard/roles/new/", {
            "name": "",
            "permissions": ["billing.view"],
        })
        assert response.status_code == 200
        self.assertContains(response, "Role name is required")

    def test_edit_custom_role(self):
        role = Role.objects.create(
            id="custom_role", organization=self.org, name="Custom",
        )
        response = self.client.get(f"/dashboard/roles/{role.id}/")
        assert response.status_code == 200
        self.assertContains(response, "Custom")

    def test_edit_default_role_redirects(self):
        owner_role = self.org.roles.get(name="Owner")
        response = self.client.get(f"/dashboard/roles/{owner_role.id}/")
        assert response.status_code == 302


class RoleDeleteTest(TestCase):

    def setUp(self):
        self.client.get("/dashboard/")
        self.account = Account.objects.get(id="test_account")
        self.org = Organization.objects.get(id="test_org")

    def test_delete_custom_role(self):
        role = Role.objects.create(
            id="del_role", organization=self.org, name="ToDelete",
        )
        response = self.client.post(f"/dashboard/roles/{role.id}/delete/")
        assert response.status_code == 302
        assert not Role.objects.filter(id="del_role").exists()

    def test_cannot_delete_default_role(self):
        owner_role = self.org.roles.get(name="Owner")
        response = self.client.post(f"/dashboard/roles/{owner_role.id}/delete/")
        assert response.status_code == 302
        assert Role.objects.filter(id=owner_role.id).exists()

    def test_cannot_delete_role_with_members(self):
        from plane.core.models import Membership
        other = Account.objects.create(id="other_mem", email="other@test.com")
        role = Role.objects.create(
            id="used_role", organization=self.org, name="InUse",
        )
        Membership.objects.create(
            id="mem_used", organization=self.org,
            account=other, role=role,
        )
        response = self.client.post(f"/dashboard/roles/{role.id}/delete/")
        assert response.status_code == 302
        assert Role.objects.filter(id="used_role").exists()


class MembersPageTest(TestCase):

    def setUp(self):
        self.client.get("/dashboard/")

    def test_returns_200(self):
        response = self.client.get("/dashboard/members/")
        assert response.status_code == 200

    def test_uses_correct_template(self):
        response = self.client.get("/dashboard/members/")
        self.assertTemplateUsed(response, "dashboard/members.html")

    def test_shows_test_member(self):
        response = self.client.get("/dashboard/members/")
        self.assertContains(response, "test@test.com")
        self.assertContains(response, "Owner")
