"""Tests for dashboard views."""

from django.test import TestCase


class IndexViewTest(TestCase):
    """Test the dashboard index/overview view."""

    def test_index_returns_200(self):
        response = self.client.get("/dashboard/")
        assert response.status_code == 200

    def test_index_uses_correct_template(self):
        response = self.client.get("/dashboard/")
        self.assertTemplateUsed(response, "dashboard/index.html")

    def test_index_extends_dashboard_layout(self):
        response = self.client.get("/dashboard/")
        self.assertTemplateUsed(response, "_layouts/dashboard.html")
        self.assertTemplateUsed(response, "base.html")

    def test_index_includes_sidebar(self):
        response = self.client.get("/dashboard/")
        self.assertTemplateUsed(response, "components/_sidebar.html")

    def test_index_shows_onboarding_banner(self):
        response = self.client.get("/dashboard/")
        self.assertContains(response, "Complete your setup")

    def test_index_shows_summary_cards(self):
        response = self.client.get("/dashboard/")
        self.assertContains(response, "API Keys")
        self.assertContains(response, "Sync Status")

    def test_index_context_has_key_summary(self):
        response = self.client.get("/dashboard/")
        assert "key_summary" in response.context

    def test_index_context_has_onboarding(self):
        response = self.client.get("/dashboard/")
        assert "onboarding" in response.context
