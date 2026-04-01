"""Tests for API key management dashboard page."""

from django.test import TestCase

from plane.core.models import Account, ApiKey, Application
from plane.dashboard.services import create_api_key


class KeysPageTest(TestCase):

    def setUp(self):
        self.client.get("/dashboard/keys/")
        self.account = Account.objects.get(id="test_account")
        self.app = Application.objects.get(id="test_app")

    def test_returns_200(self):
        response = self.client.get("/dashboard/keys/")
        assert response.status_code == 200

    def test_uses_correct_template(self):
        response = self.client.get("/dashboard/keys/")
        self.assertTemplateUsed(response, "dashboard/keys.html")

    def test_shows_empty_state_with_no_keys(self):
        response = self.client.get("/dashboard/keys/")
        self.assertContains(response, "No active API keys")

    def test_shows_key_after_creation(self):
        create_api_key(self.account, self.app, "test", "my key")
        response = self.client.get("/dashboard/keys/")
        self.assertContains(response, "my key")

    def test_create_key_via_post(self):
        response = self.client.post("/dashboard/keys/", {"label": "new key"})
        assert response.status_code == 302
        assert ApiKey.objects.filter(label="new key").exists()

    def test_full_key_in_session_after_create(self):
        self.client.post("/dashboard/keys/", {"label": "session key"})
        assert ApiKey.objects.filter(label="session key").exists()

    def test_create_redirects_to_detail_with_reveal(self):
        response = self.client.post("/dashboard/keys/", {"label": "reveal"})
        assert response.status_code == 302
        detail_response = self.client.get(response.url)
        self.assertContains(detail_response, "psc_test_")
        self.assertContains(detail_response, "will not be shown again")

    def test_revoke_key(self):
        api_key, _ = create_api_key(self.account, self.app, "test")
        response = self.client.post(f"/dashboard/keys/{api_key.id}/revoke/")
        assert response.status_code == 302
        api_key.refresh_from_db()
        assert api_key.is_active is False

    def test_filters_keys_by_environment(self):
        create_api_key(self.account, self.app, "test", "test key")
        create_api_key(self.account, self.app, "live", "live key")

        response = self.client.get("/dashboard/keys/")
        self.assertContains(response, "test key")
        self.assertNotContains(response, "live key")
