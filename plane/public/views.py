"""Public marketing page views."""

import json
from pathlib import Path

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render


def _allow_crawlers(response):
    """Mark a response as freely crawlable/fetchable.

    Docs are public and meant to be indexed and read by tools and LLM crawlers.
    We explicitly opt the docs segment into indexing (``X-Robots-Tag: all``) and
    allow cross-origin programmatic fetches (``Access-Control-Allow-Origin: *``).

    NOTE: AI-crawler 403s on this site originate at the Cloudflare edge (the
    "Block AI Scrapers and Crawlers" / Bot Fight Mode feature), not here — those
    requests never reach Django. The fix for that is a Cloudflare WAF skip rule
    scoped to ``/docs*`` (and ``/robots.txt`` / ``/llms.txt``); see
    docs/platform/cloudflare-docs-crawlers.md. These headers ensure the origin
    welcomes crawlers once the edge lets them through.
    """
    response["X-Robots-Tag"] = "all"
    response["Access-Control-Allow-Origin"] = "*"
    response["Access-Control-Allow-Methods"] = "GET, HEAD, OPTIONS"
    return response


def landing(request):
    return render(request, "public/landing.html")


def pricing(request):
    return render(request, "public/pricing.html")


def status(request):
    return render(request, "public/status.html")


def security(request):
    return render(request, "public/security.html")


def terms(request):
    return render(request, "legal/terms.html")


def privacy(request):
    return render(request, "legal/privacy.html")


def cookies(request):
    return render(request, "legal/cookies.html")


# ---------------------------------------------------------------------------
# Documentation
# ---------------------------------------------------------------------------

def _get_docs_root() -> Path:
    """Locate the pyscoped docs directory.

    Checks in order:
    1. PYSCOPED_DOCS_PATH environment variable (explicit override)
    2. Sibling pyscoped repo (development: ../pyscoped/docs)
    3. Bundled docs in the installed package (if included in wheel)
    """
    import os

    explicit = os.environ.get("PYSCOPED_DOCS_PATH")
    if explicit:
        return Path(explicit)

    # Sibling repo (common in development and Docker with mounted volumes)
    sibling = Path(__file__).resolve().parent.parent.parent / "pyscoped" / "docs"
    if sibling.exists():
        return sibling

    # Fallback: installed package
    import scoped
    return Path(scoped.__file__).parent.parent / "docs"


def _get_claude_md() -> Path:
    """Locate the CLAUDE.md file.

    Same resolution order as _get_docs_root().
    """
    import os

    explicit = os.environ.get("PYSCOPED_DOCS_PATH")
    if explicit:
        docs_path = Path(explicit)
        # CLAUDE.md lives alongside the docs/ dir (repo root)
        claude = docs_path.parent / "CLAUDE.md"
        if claude.exists():
            return claude
        # Or inside the docs path itself (Docker build copies it there)
        claude = docs_path / "CLAUDE.md"
        if claude.exists():
            return claude

    sibling = Path(__file__).resolve().parent.parent.parent / "pyscoped" / "CLAUDE.md"
    if sibling.exists():
        return sibling

    import scoped
    return Path(scoped.__file__).parent.parent / "CLAUDE.md"


def _get_agents_md() -> Path:
    """Locate the AGENTS.md file (same resolution order as _get_claude_md())."""
    import os

    explicit = os.environ.get("PYSCOPED_DOCS_PATH")
    if explicit:
        docs_path = Path(explicit)
        agents = docs_path.parent / "AGENTS.md"
        if agents.exists():
            return agents
        agents = docs_path / "AGENTS.md"
        if agents.exists():
            return agents

    sibling = Path(__file__).resolve().parent.parent.parent / "pyscoped" / "AGENTS.md"
    if sibling.exists():
        return sibling

    import scoped
    return Path(scoped.__file__).parent.parent / "AGENTS.md"


def docs(request):
    """Documentation hub — renders the manifest as a navigable page."""
    docs_root = _get_docs_root()
    manifest_path = docs_root / "manifest.json"

    sdk_categories = []
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        cat_map = {c["id"]: {**c, "pages": []} for c in manifest.get("categories", [])}
        for page in manifest.get("pages", []):
            cat_id = page.get("category", "guide")
            if cat_id in cat_map:
                cat_map[cat_id]["pages"].append(page)
        sdk_categories = sorted(cat_map.values(), key=lambda c: c.get("order", 99))

    # Platform docs
    platform_manifest = _get_platform_docs_root() / "manifest.json"
    platform_categories = []
    if platform_manifest.exists():
        p_manifest = json.loads(platform_manifest.read_text())
        p_cat_map = {c["id"]: {**c, "pages": []} for c in p_manifest.get("categories", [])}
        for page in p_manifest.get("pages", []):
            page["path"] = f"platform/{page['path']}"
            cat_id = page.get("category", "api")
            if cat_id in p_cat_map:
                p_cat_map[cat_id]["pages"].append(page)
        platform_categories = sorted(p_cat_map.values(), key=lambda c: c.get("order", 99))

    return render(request, "public/docs.html", {
        "sdk_categories": sdk_categories,
        "platform_categories": platform_categories,
        "has_docs": bool(sdk_categories) or bool(platform_categories),
    })


def docs_page(request, path):
    """Render a single documentation page as markdown."""
    docs_root = _get_docs_root()
    # Sanitize: only allow .md files under docs/
    safe_path = Path(path)
    if ".." in safe_path.parts or not str(safe_path).endswith(".md"):
        return HttpResponse("Not found", status=404)

    file_path = docs_root / safe_path
    if not file_path.exists() or not file_path.is_file():
        return HttpResponse("Not found", status=404)

    content = file_path.read_text()

    # Strip YAML frontmatter for display
    title = safe_path.stem.replace("-", " ").title()
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            # Parse title from frontmatter
            for line in parts[1].strip().split("\n"):
                if line.startswith("title:"):
                    title = line.split(":", 1)[1].strip().strip('"').strip("'")
                    break
            content = parts[2].strip()

    return render(request, "public/docs_page.html", {
        "title": title,
        "content": content,
        "path": path,
    })


def docs_manifest(request):
    """Serve the docs manifest.json for programmatic access."""
    docs_root = _get_docs_root()
    manifest_path = docs_root / "manifest.json"
    if not manifest_path.exists():
        return JsonResponse({"error": "Manifest not found"}, status=404)
    return _allow_crawlers(JsonResponse(json.loads(manifest_path.read_text())))


def docs_raw(request, path):
    """Serve a raw markdown file for programmatic access."""
    docs_root = _get_docs_root()
    safe_path = Path(path)
    if ".." in safe_path.parts or not str(safe_path).endswith(".md"):
        return HttpResponse("Not found", status=404, content_type="text/plain")

    file_path = docs_root / safe_path
    if not file_path.exists() or not file_path.is_file():
        return HttpResponse("Not found", status=404, content_type="text/plain")

    return _allow_crawlers(
        HttpResponse(file_path.read_text(), content_type="text/markdown; charset=utf-8")
    )


def claude_md(request):
    """Serve CLAUDE.md for LLM workspace export."""
    path = _get_claude_md()
    if not path.exists():
        return HttpResponse("CLAUDE.md not found", status=404, content_type="text/plain")
    response = HttpResponse(path.read_text(), content_type="text/markdown; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="CLAUDE.md"'
    return _allow_crawlers(response)


def agents_md(request):
    """Serve AGENTS.md for LLM/agent workspace export (vendor-neutral CLAUDE.md)."""
    path = _get_agents_md()
    if not path.exists():
        return HttpResponse("AGENTS.md not found", status=404, content_type="text/plain")
    response = HttpResponse(path.read_text(), content_type="text/markdown; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="AGENTS.md"'
    return _allow_crawlers(response)


def _get_platform_docs_root() -> Path:
    """Locate the platform's own docs directory."""
    return Path(__file__).resolve().parent.parent.parent / "docs" / "platform"


def platform_docs_manifest(request):
    """Serve the platform docs manifest.json."""
    manifest_path = _get_platform_docs_root() / "manifest.json"
    if not manifest_path.exists():
        return JsonResponse({"error": "Manifest not found"}, status=404)
    return _allow_crawlers(JsonResponse(json.loads(manifest_path.read_text())))


def platform_docs_page(request, path):
    """Render a platform documentation page."""
    docs_root = _get_platform_docs_root()
    safe_path = Path(path)
    if ".." in safe_path.parts or not str(safe_path).endswith(".md"):
        return HttpResponse("Not found", status=404)

    file_path = docs_root / safe_path
    if not file_path.exists() or not file_path.is_file():
        return HttpResponse("Not found", status=404)

    content = file_path.read_text()
    title = safe_path.stem.replace("-", " ").title()
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].strip().split("\n"):
                if line.startswith("title:"):
                    title = line.split(":", 1)[1].strip().strip('"').strip("'")
                    break
            content = parts[2].strip()

    return render(request, "public/docs_page.html", {
        "title": title,
        "content": content,
        "path": f"platform/{path}",
        "is_platform": True,
    })


def platform_docs_raw(request, path):
    """Serve a raw platform markdown file."""
    docs_root = _get_platform_docs_root()
    safe_path = Path(path)
    if ".." in safe_path.parts or not str(safe_path).endswith(".md"):
        return HttpResponse("Not found", status=404, content_type="text/plain")

    file_path = docs_root / safe_path
    if not file_path.exists() or not file_path.is_file():
        return HttpResponse("Not found", status=404, content_type="text/plain")

    return _allow_crawlers(
        HttpResponse(file_path.read_text(), content_type="text/markdown; charset=utf-8")
    )


# ---------------------------------------------------------------------------
# Crawler discovery — robots.txt and llms.txt
# ---------------------------------------------------------------------------

# AI / LLM crawler user-agents we explicitly welcome on the docs segment.
_AI_CRAWLERS = [
    "GPTBot", "OAI-SearchBot", "ChatGPT-User",
    "ClaudeBot", "Claude-User", "Claude-SearchBot", "anthropic-ai",
    "PerplexityBot", "Perplexity-User",
    "Google-Extended", "CCBot", "Applebot-Extended",
    "Amazonbot", "Bytespider", "Meta-ExternalAgent", "cohere-ai",
]


def robots_txt(request):
    """Serve robots.txt.

    Crawlers (including AI/LLM crawlers) are welcome on the public docs and the
    CLAUDE.md / AGENTS.md exports, but not on the dashboard, admin, API, or auth
    pages. Note: actual AI-bot blocking happens at Cloudflare's edge, not here —
    this file states intent; the enforcement change is a Cloudflare WAF skip rule
    for /docs (see docs/platform/cloudflare-docs-crawlers.md).
    """
    disallow = ["/dashboard/", "/admin/", "/v1/", "/webhooks/", "/sign-in", "/sign-up"]
    allow_docs = ["/docs", "/llms.txt", "/static/"]

    lines = ["# pyscoped — https://kwip.tech", ""]

    # AI crawlers: explicitly allow the docs segment, disallow the app.
    for agent in _AI_CRAWLERS:
        lines.append(f"User-agent: {agent}")
        for path in allow_docs:
            lines.append(f"Allow: {path}")
        for path in disallow:
            lines.append(f"Disallow: {path}")
        lines.append("")

    # Everyone else.
    lines.append("User-agent: *")
    for path in disallow:
        lines.append(f"Disallow: {path}")
    lines.append("")
    # LLM-discovery index (llmstxt.org). Not an XML sitemap, so it's advertised
    # as a comment rather than a Sitemap: directive.
    lines.append(f"# LLM index: {request.build_absolute_uri('/llms.txt')}")
    lines.append("")

    return _allow_crawlers(
        HttpResponse("\n".join(lines), content_type="text/plain; charset=utf-8")
    )


def llms_txt(request):
    """Serve /llms.txt — an LLM-friendly index of the docs (llmstxt.org standard)."""
    base = request.build_absolute_uri("/").rstrip("/")
    body = f"""# pyscoped

> Universal object-isolation and tenancy-scoping framework for Python. Creator-private
> by default, explicit sharing via scopes, versioned mutations, and a tamper-evident
> hash-chained audit trail.

## Agent & LLM context

- [CLAUDE.md]({base}/docs/claude.md): Full framework reference for AI assistants
- [AGENTS.md]({base}/docs/agents.md): Vendor-neutral agent guide (incl. pyscoped[django] integration)

## Docs

- [Documentation hub]({base}/docs): SDK reference, platform guides, integration examples
- [SDK docs index]({base}/docs/manifest.json): Machine-readable SDK docs manifest
- [Platform docs index]({base}/docs/platform/manifest.json): Machine-readable platform docs manifest

## Raw markdown

- SDK pages: {base}/docs/raw/<path>
- Platform pages: {base}/docs/platform/raw/<path>
"""
    return _allow_crawlers(
        HttpResponse(body, content_type="text/markdown; charset=utf-8")
    )


def sign_in(request, rest=None):
    """Sign-in page with embedded Clerk SignIn component."""
    return render(request, "auth/sign_in.html")


def sign_up(request, rest=None):
    """Sign-up page with embedded Clerk SignUp component."""
    return render(request, "auth/sign_up.html")
