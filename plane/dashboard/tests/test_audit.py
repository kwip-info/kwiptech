"""Tests for the audit trail viewer page."""

from django.test import TestCase


class AuditTrailPageTest(TestCase):

    def test_returns_200(self):
        response = self.client.get("/dashboard/audit/")
        assert response.status_code == 200

    def test_uses_correct_template(self):
        response = self.client.get("/dashboard/audit/")
        self.assertTemplateUsed(response, "dashboard/audit.html")

    def test_shows_empty_state_with_no_entries(self):
        response = self.client.get("/dashboard/audit/")
        self.assertContains(response, "No audit entries")

    def test_has_filter_form(self):
        response = self.client.get("/dashboard/audit/")
        self.assertContains(response, "Action")
        self.assertContains(response, "Target")
        self.assertContains(response, "Search")

    def test_filter_params_preserved(self):
        response = self.client.get("/dashboard/audit/?action=create")
        assert response.context["filters"]["action"] == "create"

    def test_context_has_entries(self):
        response = self.client.get("/dashboard/audit/")
        assert "entries" in response.context

    def test_context_has_filters(self):
        response = self.client.get("/dashboard/audit/")
        assert "filters" in response.context
