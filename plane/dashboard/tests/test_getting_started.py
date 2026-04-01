"""Tests for the getting started onboarding page."""

from django.test import TestCase

from plane.core.models import Account, Application
from plane.dashboard.services import create_api_key


class GettingStartedPageTest(TestCase):

    def setUp(self):
        self.client.get("/dashboard/getting-started/")
        self.account = Account.objects.get(id="test_account")
        self.app = Application.objects.get(id="test_app")

    def test_returns_200(self):
        response = self.client.get("/dashboard/getting-started/")
        assert response.status_code == 200

    def test_uses_correct_template(self):
        response = self.client.get("/dashboard/getting-started/")
        self.assertTemplateUsed(response, "dashboard/getting_started.html")

    def test_shows_sdk_install_snippet(self):
        response = self.client.get("/dashboard/getting-started/")
        self.assertContains(response, "pip install pyscoped")

    def test_shows_init_snippet(self):
        response = self.client.get("/dashboard/getting-started/")
        self.assertContains(response, "scoped.init")

    def test_shows_create_key_step(self):
        response = self.client.get("/dashboard/getting-started/")
        self.assertContains(response, "Create an API key")

    def test_detects_key_creation_sticky(self):
        """Creating then revoking a key still shows step as done."""
        from plane.dashboard.services import revoke_api_key
        api_key, _ = create_api_key(self.account, self.app, "test")
        revoke_api_key(self.app, api_key.id)
        response = self.client.get("/dashboard/getting-started/")
        self.assertContains(response, "Create an API key")
