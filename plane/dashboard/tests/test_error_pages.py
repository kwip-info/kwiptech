"""Tests for custom error pages."""

from django.template.loader import render_to_string
from django.test import TestCase, override_settings


@override_settings(DEBUG=False, ALLOWED_HOSTS=["*"])
class NotFoundPageTest(TestCase):
    """Test 404 error page."""

    def test_returns_404_status(self):
        response = self.client.get("/nonexistent-page-that-does-not-exist/")
        assert response.status_code == 404

    def test_contains_error_message(self):
        response = self.client.get("/nonexistent-page-that-does-not-exist/")
        self.assertContains(response, "Page not found", status_code=404)

    def test_has_link_home(self):
        response = self.client.get("/nonexistent-page-that-does-not-exist/")
        self.assertContains(response, 'href="/"', status_code=404)


class ServerErrorPageTest(TestCase):
    """Test 500 error page renders without context processors."""

    def test_renders_with_empty_context(self):
        html = render_to_string("500.html")
        assert "Something went wrong" in html

    def test_has_link_home(self):
        html = render_to_string("500.html")
        assert 'href="/"' in html

    def test_is_standalone_html(self):
        html = render_to_string("500.html")
        assert "<!DOCTYPE html>" in html
