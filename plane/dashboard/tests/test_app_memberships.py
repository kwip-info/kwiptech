"""Tests for app+env scoped role overrides (AppMembership)."""

from uuid import uuid4

from django.db import IntegrityError
from django.test import TestCase

from plane.core.models import (
    Account,
    AppMembership,
    Application,
    Membership,
    Organization,
    Permission,
    Role,
)


class AppMembershipModelTest(TestCase):
    """Model-level constraints and behavior."""

    def setUp(self):
        # Bootstrap via the test middleware helper (creates test org, app, etc.)
        self.client.get("/dashboard/")
        self.org = Organization.objects.get(id="test_org")
        self.app = Application.objects.get(id="test_app")
        self.account = Account.objects.get(id="test_account")
        self.membership = Membership.objects.get(
            organization=self.org, account=self.account,
        )
        self.viewer_role = Role.objects.get(organization=self.org, name="Viewer")
        self.dev_role = Role.objects.get(organization=self.org, name="Developer")

    def test_create_override(self):
        ov = AppMembership.objects.create(
            id=uuid4().hex,
            membership=self.membership,
            application=self.app,
            environment="test",
            role=self.viewer_role,
        )
        assert ov.pk
        assert ov.environment == "test"
        assert ov.role == self.viewer_role

    def test_null_env_app_wide_override(self):
        ov = AppMembership.objects.create(
            id=uuid4().hex,
            membership=self.membership,
            application=self.app,
            environment=None,
            role=self.viewer_role,
        )
        assert ov.environment is None

    def test_unique_constraint(self):
        AppMembership.objects.create(
            id=uuid4().hex,
            membership=self.membership,
            application=self.app,
            environment="test",
            role=self.viewer_role,
        )
        with self.assertRaises(IntegrityError):
            AppMembership.objects.create(
                id=uuid4().hex,
                membership=self.membership,
                application=self.app,
                environment="test",
                role=self.dev_role,
            )

    def test_cascade_on_membership_delete(self):
        AppMembership.objects.create(
            id=uuid4().hex,
            membership=self.membership,
            application=self.app,
            environment="live",
            role=self.viewer_role,
        )
        assert AppMembership.objects.count() == 1
        self.membership.delete()
        assert AppMembership.objects.count() == 0

    def test_cascade_on_application_delete(self):
        AppMembership.objects.create(
            id=uuid4().hex,
            membership=self.membership,
            application=self.app,
            environment="test",
            role=self.viewer_role,
        )
        self.app.delete()
        assert AppMembership.objects.count() == 0


class PermissionResolutionTest(TestCase):
    """Middleware permission resolution with overrides."""

    def setUp(self):
        self.client.get("/dashboard/")
        self.org = Organization.objects.get(id="test_org")
        self.app = Application.objects.get(id="test_app")
        self.account = Account.objects.get(id="test_account")
        self.membership = Membership.objects.get(
            organization=self.org, account=self.account,
        )
        # Test account has Owner role (all permissions)
        self.viewer_role = Role.objects.get(organization=self.org, name="Viewer")

    def test_org_role_when_no_override(self):
        """Without overrides, org-level permissions apply."""
        response = self.client.get("/dashboard/")
        # Owner has all permissions — keys page should be accessible
        assert response.status_code == 200

    def test_override_restricts_permissions(self):
        """With a Viewer override, permission set is reduced."""
        AppMembership.objects.create(
            id=uuid4().hex,
            membership=self.membership,
            application=self.app,
            environment="test",
            role=self.viewer_role,
        )
        # Set the active app/env cookies to match the override
        self.client.cookies["scoped_app"] = self.app.id
        self.client.cookies["scoped_env"] = "test"

        # Viewer doesn't have keys.create — creating a key should be denied
        response = self.client.post("/dashboard/keys/", {"label": "test"})
        assert response.status_code == 403

    def test_different_env_uses_org_fallback(self):
        """Override for 'test' doesn't affect 'live' — fallback to org role."""
        AppMembership.objects.create(
            id=uuid4().hex,
            membership=self.membership,
            application=self.app,
            environment="test",
            role=self.viewer_role,
        )
        # Switch to live env — no override exists, should fall back to Owner
        self.client.cookies["scoped_app"] = self.app.id
        self.client.cookies["scoped_env"] = "live"

        response = self.client.post("/dashboard/keys/", {"label": "test"})
        # Owner can create keys — should redirect (302), not 403
        assert response.status_code in (200, 302)

    def test_app_wide_override(self):
        """env=NULL override applies to all environments."""
        AppMembership.objects.create(
            id=uuid4().hex,
            membership=self.membership,
            application=self.app,
            environment=None,
            role=self.viewer_role,
        )
        self.client.cookies["scoped_app"] = self.app.id
        self.client.cookies["scoped_env"] = "live"

        response = self.client.post("/dashboard/keys/", {"label": "test"})
        assert response.status_code == 403


class OverrideViewsTest(TestCase):
    """CRUD views for managing overrides."""

    def setUp(self):
        self.client.get("/dashboard/")
        self.org = Organization.objects.get(id="test_org")
        self.app = Application.objects.get(id="test_app")
        self.account = Account.objects.get(id="test_account")
        self.membership = Membership.objects.get(
            organization=self.org, account=self.account,
        )
        self.viewer_role = Role.objects.get(organization=self.org, name="Viewer")

    def test_members_page_shows_overrides(self):
        AppMembership.objects.create(
            id=uuid4().hex,
            membership=self.membership,
            application=self.app,
            environment="test",
            role=self.viewer_role,
        )
        response = self.client.get("/dashboard/members/")
        self.assertContains(response, "App overrides")
        self.assertContains(response, self.app.name)
        self.assertContains(response, "Viewer")

    def test_add_override(self):
        response = self.client.post(
            f"/dashboard/members/{self.membership.id}/overrides/add/",
            {
                "application": self.app.id,
                "environment": "live",
                "role": self.viewer_role.id,
            },
        )
        assert response.status_code == 302
        assert AppMembership.objects.filter(
            membership=self.membership,
            application=self.app,
            environment="live",
        ).exists()

    def test_add_duplicate_override_shows_error(self):
        # Override for "live" — manage from "test" where Owner perms apply
        AppMembership.objects.create(
            id=uuid4().hex,
            membership=self.membership,
            application=self.app,
            environment="live",
            role=self.viewer_role,
        )
        response = self.client.post(
            f"/dashboard/members/{self.membership.id}/overrides/add/",
            {
                "application": self.app.id,
                "environment": "live",
                "role": self.viewer_role.id,
            },
            follow=True,
        )
        self.assertContains(response, "already exists")

    def test_remove_override(self):
        # Override for "live" — manage from "test" where Owner perms apply
        ov = AppMembership.objects.create(
            id=uuid4().hex,
            membership=self.membership,
            application=self.app,
            environment="live",
            role=self.viewer_role,
        )
        response = self.client.post(
            f"/dashboard/members/overrides/{ov.id}/remove/",
        )
        assert response.status_code == 302
        assert not AppMembership.objects.filter(id=ov.id).exists()

    def test_members_page_shows_add_form(self):
        response = self.client.get("/dashboard/members/")
        self.assertContains(response, "Add app override")
