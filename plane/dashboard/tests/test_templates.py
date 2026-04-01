"""Tests for template infrastructure."""

from django.template.loader import get_template
from django.test import TestCase


class TemplateLoadingTest(TestCase):
    """Verify all templates can be loaded."""

    def test_base_template_loads(self):
        template = get_template("base.html")
        assert template is not None

    def test_dashboard_layout_loads(self):
        template = get_template("_layouts/dashboard.html")
        assert template is not None

    def test_public_layout_loads(self):
        template = get_template("_layouts/public.html")
        assert template is not None

    def test_all_components_load(self):
        components = [
            "components/_sidebar.html",
            "components/_header.html",
            "components/_toast.html",
            "components/_footer.html",
            "components/_empty_state.html",
        ]
        for component in components:
            template = get_template(component)
            assert template is not None, f"Failed to load {component}"


class BaseTemplateContentTest(TestCase):
    """Verify base template includes required assets."""

    def test_contains_htmx_script(self):
        response = self.client.get("/")
        self.assertContains(response, "htmx.org")

    def test_contains_alpine_script(self):
        response = self.client.get("/")
        self.assertContains(response, "alpinejs")

    def test_contains_tailwind_script(self):
        response = self.client.get("/")
        self.assertContains(response, "tailwindcss")

    def test_contains_inter_font(self):
        response = self.client.get("/")
        self.assertContains(response, "fonts.googleapis.com")

    def test_contains_favicon(self):
        response = self.client.get("/")
        self.assertContains(response, "favicon")

    def test_contains_app_css(self):
        response = self.client.get("/")
        self.assertContains(response, "app.css")

    def test_contains_app_js(self):
        response = self.client.get("/")
        self.assertContains(response, "app.js")
