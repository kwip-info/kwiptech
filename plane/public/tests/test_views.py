"""Tests for public marketing pages."""

from django.test import TestCase


class LandingPageTest(TestCase):

    def test_returns_200(self):
        response = self.client.get("/")
        assert response.status_code == 200

    def test_uses_public_layout(self):
        response = self.client.get("/")
        self.assertTemplateUsed(response, "_layouts/public.html")

    def test_contains_value_prop(self):
        response = self.client.get("/")
        self.assertContains(response, "Know what changed")

    def test_contains_signup_cta(self):
        response = self.client.get("/")
        self.assertContains(response, "Get started")


class PricingPageTest(TestCase):

    def test_returns_200(self):
        response = self.client.get("/pricing")
        assert response.status_code == 200

    def test_contains_plan_tiers(self):
        response = self.client.get("/pricing")
        self.assertContains(response, "Free")
        self.assertContains(response, "Pro")
        self.assertContains(response, "Enterprise")

    def test_contains_never_billed(self):
        response = self.client.get("/pricing")
        self.assertContains(response, "never billed")


class StatusPageTest(TestCase):

    def test_returns_200(self):
        response = self.client.get("/status")
        assert response.status_code == 200

    def test_contains_htmx_ping(self):
        response = self.client.get("/status")
        self.assertContains(response, 'hx-get="/v1/ping"')

    def test_contains_auto_refresh(self):
        response = self.client.get("/status")
        self.assertContains(response, "every 30s")


class SecurityPageTest(TestCase):

    def test_returns_200(self):
        response = self.client.get("/security")
        assert response.status_code == 200

    def test_contains_architecture_section(self):
        response = self.client.get("/security")
        self.assertContains(response, "Architecture")

    def test_contains_data_residency(self):
        response = self.client.get("/security")
        self.assertContains(response, "Data residency")

    def test_contains_invariants(self):
        response = self.client.get("/security")
        self.assertContains(response, "Nothing happens without a trace")


class LegalPageTest(TestCase):

    def test_terms_returns_200(self):
        response = self.client.get("/terms")
        assert response.status_code == 200

    def test_terms_contains_heading(self):
        response = self.client.get("/terms")
        self.assertContains(response, "Terms of Service")

    def test_privacy_returns_200(self):
        response = self.client.get("/privacy")
        assert response.status_code == 200

    def test_privacy_contains_heading(self):
        response = self.client.get("/privacy")
        self.assertContains(response, "Privacy Policy")

    def test_cookies_returns_200(self):
        response = self.client.get("/cookies")
        assert response.status_code == 200

    def test_cookies_contains_heading(self):
        response = self.client.get("/cookies")
        self.assertContains(response, "Cookie Policy")


class AuthPageRoutingTest(TestCase):

    def test_sign_in_returns_200(self):
        response = self.client.get("/sign-in")
        assert response.status_code == 200

    def test_sign_up_returns_200(self):
        response = self.client.get("/sign-up")
        assert response.status_code == 200

    def test_sign_in_sub_path_returns_200(self):
        response = self.client.get("/sign-in/factor-one")
        assert response.status_code == 200
