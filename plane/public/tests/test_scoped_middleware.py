"""Regression tests for public-route scoped middleware exemptions."""

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from plane.middleware import PlatformScopedContextMiddleware


@override_settings(
    SCOPED_EXEMPT_PATHS=["/docs"],
    SCOPED_EXEMPT_EXACT_PATHS=["/"],
)
class PlatformScopedContextMiddlewareTest(SimpleTestCase):
    def setUp(self):
        self.middleware = PlatformScopedContextMiddleware(
            lambda request: HttpResponse()
        )
        self.factory = RequestFactory()

    def test_landing_page_is_exempt(self):
        assert self.middleware._is_exempt(self.factory.get("/"))

    def test_root_exemption_does_not_exempt_application_routes(self):
        assert not self.middleware._is_exempt(self.factory.get("/dashboard/"))

    def test_existing_prefix_exemptions_still_work(self):
        assert self.middleware._is_exempt(self.factory.get("/docs/getting-started"))
