"""Public marketing page views."""

import json
from pathlib import Path

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render


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
    return JsonResponse(json.loads(manifest_path.read_text()))


def docs_raw(request, path):
    """Serve a raw markdown file for programmatic access."""
    docs_root = _get_docs_root()
    safe_path = Path(path)
    if ".." in safe_path.parts or not str(safe_path).endswith(".md"):
        return HttpResponse("Not found", status=404, content_type="text/plain")

    file_path = docs_root / safe_path
    if not file_path.exists() or not file_path.is_file():
        return HttpResponse("Not found", status=404, content_type="text/plain")

    return HttpResponse(file_path.read_text(), content_type="text/markdown; charset=utf-8")


def claude_md(request):
    """Serve CLAUDE.md for LLM workspace export."""
    path = _get_claude_md()
    if not path.exists():
        return HttpResponse("CLAUDE.md not found", status=404, content_type="text/plain")
    response = HttpResponse(path.read_text(), content_type="text/markdown; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="CLAUDE.md"'
    return response


def _get_platform_docs_root() -> Path:
    """Locate the platform's own docs directory."""
    return Path(__file__).resolve().parent.parent.parent / "docs" / "platform"


def platform_docs_manifest(request):
    """Serve the platform docs manifest.json."""
    manifest_path = _get_platform_docs_root() / "manifest.json"
    if not manifest_path.exists():
        return JsonResponse({"error": "Manifest not found"}, status=404)
    return JsonResponse(json.loads(manifest_path.read_text()))


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

    return HttpResponse(file_path.read_text(), content_type="text/markdown; charset=utf-8")


def sign_in(request, rest=None):
    """Sign-in page with embedded Clerk SignIn component."""
    return render(request, "auth/sign_in.html")


def sign_up(request, rest=None):
    """Sign-up page with embedded Clerk SignUp component."""
    return render(request, "auth/sign_up.html")
