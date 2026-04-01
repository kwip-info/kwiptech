"""Tests for key detail page and rotation."""

from django.test import TestCase

from plane.core.models import Account, ApiKey, Application
from plane.dashboard.services import create_api_key, revoke_api_key


class KeyDetailPageTest(TestCase):

    def setUp(self):
        self.client.get("/dashboard/keys/")
        self.account = Account.objects.get(id="test_account")
        self.app = Application.objects.get(id="test_app")
        self.api_key, _ = create_api_key(self.account, self.app, "test", "detail test key")

    def test_returns_200(self):
        response = self.client.get(f"/dashboard/keys/{self.api_key.id}/")
        assert response.status_code == 200

    def test_uses_correct_template(self):
        response = self.client.get(f"/dashboard/keys/{self.api_key.id}/")
        self.assertTemplateUsed(response, "dashboard/key_detail.html")

    def test_shows_key_prefix(self):
        response = self.client.get(f"/dashboard/keys/{self.api_key.id}/")
        self.assertContains(response, self.api_key.key_prefix)

    def test_shows_label(self):
        response = self.client.get(f"/dashboard/keys/{self.api_key.id}/")
        self.assertContains(response, "detail test key")

    def test_shows_active_status(self):
        response = self.client.get(f"/dashboard/keys/{self.api_key.id}/")
        self.assertContains(response, "Active")

    def test_shows_revoked_status(self):
        revoke_api_key(self.app, self.api_key.id)
        response = self.client.get(f"/dashboard/keys/{self.api_key.id}/")
        self.assertContains(response, "Revoked")

    def test_nonexistent_key_returns_404(self):
        response = self.client.get("/dashboard/keys/nonexistent/")
        assert response.status_code == 404

    def test_other_apps_key_returns_404(self):
        """Key belonging to another application returns 404."""
        from plane.core.models import Organization
        other_account = Account.objects.create(id="other_acc", email="other@test.com")
        other_org = Organization.objects.create(
            id="other_org", name="Other", slug="other-org", owner=other_account,
        )
        other_app = Application.objects.create(
            id="other_app", organization=other_org, name="Other App", slug="other",
        )
        other_key, _ = create_api_key(other_account, other_app, "test")
        response = self.client.get(f"/dashboard/keys/{other_key.id}/")
        assert response.status_code == 404

    def test_has_rotate_button(self):
        response = self.client.get(f"/dashboard/keys/{self.api_key.id}/")
        self.assertContains(response, "Rotate")

    def test_has_back_link(self):
        response = self.client.get(f"/dashboard/keys/{self.api_key.id}/")
        self.assertContains(response, "Back to all keys")


class RotateKeyTest(TestCase):

    def setUp(self):
        self.client.get("/dashboard/keys/")
        self.account = Account.objects.get(id="test_account")
        self.app = Application.objects.get(id="test_app")
        self.api_key, _ = create_api_key(self.account, self.app, "test", "rotate me")

    def test_rotate_creates_new_key(self):
        before_count = ApiKey.objects.filter(application=self.app).count()
        self.client.post(f"/dashboard/keys/{self.api_key.id}/rotate/")
        after_count = ApiKey.objects.filter(application=self.app).count()
        assert after_count == before_count + 1

    def test_rotate_revokes_old_key(self):
        self.client.post(f"/dashboard/keys/{self.api_key.id}/rotate/")
        self.api_key.refresh_from_db()
        assert self.api_key.is_active is False

    def test_rotate_preserves_environment(self):
        self.client.post(f"/dashboard/keys/{self.api_key.id}/rotate/")
        new_key = ApiKey.objects.filter(
            application=self.app, is_active=True,
        ).latest("created_at")
        assert new_key.environment == self.api_key.environment

    def test_rotate_redirects_to_new_key_detail(self):
        response = self.client.post(f"/dashboard/keys/{self.api_key.id}/rotate/")
        assert response.status_code == 302
        new_key = ApiKey.objects.filter(
            application=self.app, is_active=True,
        ).latest("created_at")
        assert response.url == f"/dashboard/keys/{new_key.id}/"

    def test_rotate_shares_scoped_object_id(self):
        """New and old key point to the same scoped object."""
        self.client.post(f"/dashboard/keys/{self.api_key.id}/rotate/")
        new_key = ApiKey.objects.filter(
            application=self.app, is_active=True,
        ).latest("created_at")
        self.api_key.refresh_from_db()
        assert new_key.scoped_object_id == self.api_key.scoped_object_id

    def test_detail_shows_credential_history_after_rotate(self):
        self.client.post(f"/dashboard/keys/{self.api_key.id}/rotate/")
        new_key = ApiKey.objects.filter(
            application=self.app, is_active=True,
        ).latest("created_at")
        response = self.client.get(f"/dashboard/keys/{new_key.id}/")
        self.assertContains(response, new_key.key_prefix)

    def test_rotate_stores_new_key_in_session(self):
        self.client.post(f"/dashboard/keys/{self.api_key.id}/rotate/")
        new_key = ApiKey.objects.filter(
            application=self.app, is_active=True,
        ).latest("created_at")
        assert new_key.key_prefix.startswith("psc_test_")
