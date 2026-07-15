"""Tests for public marketing pages."""

import tempfile
from pathlib import Path
from unittest import mock

from django.test import TestCase

from plane.public.models import DigestPilotLead


class LandingPageTest(TestCase):

    def test_returns_200(self):
        response = self.client.get("/")
        assert response.status_code == 200

    def test_uses_public_layout(self):
        response = self.client.get("/")
        self.assertTemplateUsed(response, "_layouts/public.html")

    def test_contains_value_prop(self):
        response = self.client.get("/")
        self.assertContains(response, "Kwip technology solutions")
        self.assertContains(response, "Current catalog")

    def test_contains_signup_cta(self):
        response = self.client.get("/")
        self.assertContains(response, "Request pilot access")


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

    def test_contains_digest_runtime_pricing(self):
        response = self.client.get("/pricing")
        self.assertContains(response, "Digest runtime licensing")
        self.assertContains(response, "$3,000-$7,500")


class DigestPageTest(TestCase):

    def test_returns_200(self):
        response = self.client.get("/digest")
        assert response.status_code == 200

    def test_contains_positioning(self):
        response = self.client.get("/digest")
        self.assertContains(response, "Universal Document Extraction Runtime")
        self.assertContains(response, "No document storage")
        self.assertContains(response, "Start a paid pilot")

    def test_links_to_docs(self):
        response = self.client.get("/digest")
        self.assertContains(response, "/docs/platform/digest-runtime.md")

    def test_pilot_form_creates_admin_visible_lead(self):
        response = self.client.post(
            "/digest",
            {
                "name": "Taylor Morgan",
                "email": "taylor@example.com",
                "company": "ExampleCo",
                "role": "Operations",
                "document_types": "PDFs and scanned images",
                "deployment_target": "kubernetes",
                "timeline": "30_days",
                "use_case": "Extract private intake documents before search indexing.",
                "website": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/digest")
        lead = DigestPilotLead.objects.get()
        self.assertEqual(lead.name, "Taylor Morgan")
        self.assertEqual(lead.email, "taylor@example.com")
        self.assertEqual(lead.company, "ExampleCo")
        self.assertEqual(lead.document_types, "PDFs and scanned images")
        self.assertEqual(lead.deployment_target, "kubernetes")
        self.assertEqual(lead.status, DigestPilotLead.Status.NEW)

    def test_pilot_form_requires_core_fields(self):
        response = self.client.post("/digest", {"website": ""})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This field is required")
        self.assertEqual(DigestPilotLead.objects.count(), 0)


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
        self.assertContains(response, "Product security architecture")

    def test_contains_data_residency(self):
        response = self.client.get("/security")
        self.assertContains(response, "Data residency")

    def test_contains_digest_runtime_boundary(self):
        response = self.client.get("/security")
        self.assertContains(response, "Digest runtime boundary")

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


class AgentContextDownloadTest(TestCase):
    """CLAUDE.md and AGENTS.md downloads for LLM/agent workspaces."""

    def _serve(self, view_path, filename):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / filename
            f.write_text(f"# {filename}\nhello")
            with mock.patch(view_path, return_value=f):
                return self.client.get(f"/docs/{filename.lower()}")

    def test_claude_md_downloads(self):
        resp = self._serve("plane.public.views._get_claude_md", "CLAUDE.md")
        assert resp.status_code == 200
        self.assertEqual(resp["Content-Disposition"], 'attachment; filename="CLAUDE.md"')
        self.assertIn("markdown", resp["Content-Type"])

    def test_agents_md_downloads(self):
        resp = self._serve("plane.public.views._get_agents_md", "AGENTS.md")
        assert resp.status_code == 200
        self.assertEqual(resp["Content-Disposition"], 'attachment; filename="AGENTS.md"')
        self.assertIn("markdown", resp["Content-Type"])

    def test_agents_md_is_crawlable(self):
        resp = self._serve("plane.public.views._get_agents_md", "AGENTS.md")
        self.assertEqual(resp["X-Robots-Tag"], "all")
        self.assertEqual(resp["Access-Control-Allow-Origin"], "*")

    def test_agents_md_missing_returns_404(self):
        with mock.patch(
            "plane.public.views._get_agents_md", return_value=Path("/nope/AGENTS.md")
        ):
            resp = self.client.get("/docs/agents.md")
        assert resp.status_code == 404


class CrawlerDiscoveryTest(TestCase):
    """robots.txt and llms.txt welcome crawlers on the docs segment."""

    def test_robots_txt_returns_200(self):
        resp = self.client.get("/robots.txt")
        assert resp.status_code == 200
        self.assertIn("text/plain", resp["Content-Type"])

    def test_robots_allows_ai_crawlers_on_docs(self):
        body = self.client.get("/robots.txt").content.decode()
        self.assertIn("User-agent: ClaudeBot", body)
        self.assertIn("User-agent: GPTBot", body)
        self.assertIn("Allow: /docs", body)

    def test_robots_disallows_app_segments(self):
        body = self.client.get("/robots.txt").content.decode()
        self.assertIn("Disallow: /dashboard/", body)
        self.assertIn("Disallow: /admin/", body)
        self.assertIn("Disallow: /v1/", body)

    def test_llms_txt_returns_200_and_links_context(self):
        resp = self.client.get("/llms.txt")
        assert resp.status_code == 200
        body = resp.content.decode()
        self.assertIn("/docs/claude.md", body)
        self.assertIn("/docs/agents.md", body)
        self.assertIn("/digest", body)
        self.assertIn("/docs/platform/digest-runtime.md", body)

    def test_discovery_files_are_crawlable(self):
        for url in ("/robots.txt", "/llms.txt"):
            resp = self.client.get(url)
            self.assertEqual(resp["X-Robots-Tag"], "all", url)


class PlatformDocsManifestTest(TestCase):

    def test_includes_digest_runtime_doc(self):
        resp = self.client.get("/docs/platform/manifest.json")
        assert resp.status_code == 200
        page_paths = [page["path"] for page in resp.json()["pages"]]
        self.assertIn("digest-runtime.md", page_paths)
