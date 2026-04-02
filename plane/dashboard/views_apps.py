"""Application management views — list, create, edit, delete."""

from uuid import uuid4

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify

from plane.core.models import Application
from plane.dashboard import services
from plane.dashboard.views import require_permission


def _actor(request):
    account = getattr(request, "clerk_user", None)
    return account.id if account else "system"


@require_permission("apps.view")
def applications(request):
    """Application list page."""
    org = request.organization
    app_list = org.applications.order_by("-is_default", "name") if org else []
    active_app = services.get_active_app(request)
    return render(request, "dashboard/applications.html", {
        "page_title": "Applications",
        "page_subtitle": "Manage your applications",
        "apps": app_list,
        "active_app": active_app,
    })


@require_permission("apps.create")
def create_application(request):
    """Create a new application."""
    org = request.organization
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        if not name:
            messages.error(request, "Application name is required.")
            return render(request, "dashboard/application_form.html", {
                "page_title": "New Application",
                "page_subtitle": "Create an application",
                "form_name": name,
            })

        slug = _unique_app_slug(org, slugify(name))
        app = Application.objects.create(
            id=uuid4().hex,
            organization=org,
            name=name,
            slug=slug,
        )

        app.sync_to_scoped()

        messages.success(request, f"Application \"{app.name}\" created.")
        response = redirect("dashboard:applications")
        response.set_cookie(
            "scoped_app", app.id,
            max_age=60 * 60 * 24 * 365, samesite="Lax",
        )
        return response

    return render(request, "dashboard/application_form.html", {
        "page_title": "New Application",
        "page_subtitle": "Create an application",
    })


@require_permission("apps.manage")
def edit_application(request, app_id):
    """Edit an application's name."""
    org = request.organization
    app = get_object_or_404(Application, id=app_id, organization=org)

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        if not name:
            messages.error(request, "Application name is required.")
        else:
            app.name = name
            app.save(update_fields=["name"])
            app.sync_to_scoped(updated_by=_actor(request))
            messages.success(request, "Application updated.")
        return redirect("dashboard:applications")

    return render(request, "dashboard/application_form.html", {
        "page_title": app.name,
        "page_subtitle": "Edit application",
        "app": app,
        "form_name": app.name,
    })


@require_permission("apps.manage")
def delete_application(request, app_id):
    """Delete an application — blocked for the default app."""
    org = request.organization
    app = get_object_or_404(Application, id=app_id, organization=org)

    if app.is_default:
        messages.error(request, "The default application cannot be deleted.")
        return redirect("dashboard:applications")

    if app.api_keys.filter(is_active=True).exists():
        messages.error(
            request,
            f"Application \"{app.name}\" has active API keys. Revoke them first.",
        )
        return redirect("dashboard:applications")

    if request.method == "POST":
        name = app.name
        app.archive_in_scoped(archived_by=_actor(request))
        app.delete()
        messages.success(request, f"Application \"{name}\" deleted.")
        response = redirect("dashboard:applications")
        response.delete_cookie("scoped_app")
        return response

    return redirect("dashboard:applications")


def _unique_app_slug(org, base_slug):
    """Ensure slug uniqueness within the org."""
    slug = base_slug
    counter = 1
    while org.applications.filter(slug=slug).exists():
        slug = f"{base_slug}-{counter}"
        counter += 1
    return slug
