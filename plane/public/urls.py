"""Public page URL configuration."""

from django.urls import path

from plane.public import views

app_name = "public"

urlpatterns = [
    path("", views.landing, name="landing"),
    path("pricing", views.pricing, name="pricing"),
    path("status", views.status, name="status"),
    path("security", views.security, name="security"),
    path("terms", views.terms, name="terms"),
    path("privacy", views.privacy, name="privacy"),
    path("cookies", views.cookies, name="cookies"),
    # Crawler discovery
    path("robots.txt", views.robots_txt, name="robots_txt"),
    path("llms.txt", views.llms_txt, name="llms_txt"),
    # Documentation
    path("docs", views.docs, name="docs"),
    path("docs/manifest.json", views.docs_manifest, name="docs_manifest"),
    path("docs/claude.md", views.claude_md, name="claude_md"),
    path("docs/agents.md", views.agents_md, name="agents_md"),
    path("docs/raw/<path:path>", views.docs_raw, name="docs_raw"),
    # Platform docs (served from local docs/platform/)
    path("docs/platform/manifest.json", views.platform_docs_manifest, name="platform_docs_manifest"),
    path("docs/platform/raw/<path:path>", views.platform_docs_raw, name="platform_docs_raw"),
    path("docs/platform/<path:path>", views.platform_docs_page, name="platform_docs_page"),
    # SDK docs (served from pyscoped package)
    path("docs/<path:path>", views.docs_page, name="docs_page"),
    # Auth
    path("sign-in", views.sign_in, name="sign_in"),
    path("sign-up", views.sign_up, name="sign_up"),
    path("sign-in/<path:rest>", views.sign_in, name="sign_in_step"),
    path("sign-up/<path:rest>", views.sign_up, name="sign_up_step"),
]
