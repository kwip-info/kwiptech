"""Tests for auth page rendering and Clerk integration."""

from django.test import TestCase, override_settings


class SignInPageTest(TestCase):

    def test_renders_200(self):
        response = self.client.get("/sign-in")
        assert response.status_code == 200

    def test_contains_clerk_mount_point(self):
        response = self.client.get("/sign-in")
        self.assertContains(response, 'id="clerk-sign-in"')

    def test_sub_path_renders(self):
        response = self.client.get("/sign-in/verify-email-address")
        assert response.status_code == 200

    def test_uses_public_layout(self):
        response = self.client.get("/sign-in")
        self.assertTemplateUsed(response, "_layouts/public.html")


class SignUpPageTest(TestCase):

    def test_renders_200(self):
        response = self.client.get("/sign-up")
        assert response.status_code == 200

    def test_contains_clerk_mount_point(self):
        response = self.client.get("/sign-up")
        self.assertContains(response, 'id="clerk-sign-up"')

    def test_sub_path_renders(self):
        response = self.client.get("/sign-up/verify-email-address")
        assert response.status_code == 200


@override_settings(CLERK_PUBLISHABLE_KEY="pk_test_abc123")
class ClerkContextProcessorTest(TestCase):

    def test_publishable_key_in_context(self):
        response = self.client.get("/sign-in")
        assert response.context["CLERK_PUBLISHABLE_KEY"] == "pk_test_abc123"

    def test_publishable_key_in_rendered_html(self):
        response = self.client.get("/sign-in")
        self.assertContains(response, "pk_test_abc123")

    def test_clerk_script_tag_rendered(self):
        response = self.client.get("/sign-in")
        self.assertContains(response, "clerk-js")
