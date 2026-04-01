"""Dashboard views."""

import functools

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render

from plane.dashboard import services
from plane.dashboard import services_analytics as analytics


def require_permission(permission_id):
    """Decorator that checks if the current user has a permission."""
    def decorator(view_func):
        @functools.wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if permission_id not in getattr(request, "permissions", set()):
                raise PermissionDenied
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


def index(request):
    """Dashboard overview with summary cards, activity feed, and charts."""
    org = request.organization
    app = services.get_active_app(request)
    env = services.get_active_env(request)
    ctx = {
        "page_title": "Dashboard",
        "page_subtitle": "Overview",
        "active_env": env,
        "active_app": app,
        "sync_status": services.get_sync_status(org) if org else None,
        "usage_summary": services.get_usage_summary(org) if org else None,
        "onboarding": services.get_onboarding_status(org) if org else None,
        "recent_activity": analytics.get_recent_activity(org) if org else [],
        "audit_count_today": analytics.get_audit_count_today(org) if org else 0,
        "env_breakdown": analytics.to_json(analytics.get_env_breakdown(app)),
        "key_activity": analytics.to_json(analytics.get_key_activity_series(app)),
        "resource_trends": analytics.to_json(
            analytics.get_resource_trend_series(org)
        ) if org else "null",
        "audit_volume": analytics.to_json(
            analytics.get_audit_volume_series(org)
        ) if org else "null",
    }
    if app:
        ctx["key_summary"] = services.get_key_summary(app, env)
    return render(request, "dashboard/index.html", ctx)


def keys(request):
    """API key management — list, create, reveal."""
    account = request.clerk_user
    app = services.get_active_app(request)
    env = services.get_active_env(request)

    if request.method == "POST":
        if "keys.create" not in getattr(request, "permissions", set()):
            raise PermissionDenied
        label = request.POST.get("label", "").strip()
        api_key, full_key = services.create_api_key(
            account, app, env, label, request=request,
        )
        request.session["pending_key"] = full_key
        request.session["pending_key_id"] = api_key.id
        return redirect("dashboard:key_detail", key_id=api_key.id)

    show_revoked = request.GET.get("show_revoked") == "1"
    page = request.GET.get("page", 1)
    keys_page = services.get_keys(app, env, show_revoked=show_revoked, page=page) if app else []

    return render(request, "dashboard/keys.html", {
        "page_title": "API Keys",
        "page_subtitle": env.capitalize() + " environment",
        "active_env": env,
        "active_app": app,
        "keys": keys_page,
        "show_revoked": show_revoked,
    })


@require_permission("keys.revoke")
def revoke_key(request, key_id):
    """Revoke an API key."""
    if request.method == "POST":
        app = services.get_active_app(request)
        if app:
            services.revoke_api_key(app, key_id, request=request)
            messages.success(request, "API key revoked.")
    return redirect("dashboard:keys")


def key_detail(request, key_id):
    """API key detail page — metadata, version history, audit trail."""
    app = services.get_active_app(request)
    api_key = services.get_key_detail(app, key_id) if app else None
    if api_key is None:
        from django.http import Http404
        raise Http404

    related_keys = services.get_related_keys(api_key)
    pending_ref = request.session.pop("pending_key", None)
    pending_key_id = request.session.pop("pending_key_id", None)

    pending_key = services.resolve_key_secret(pending_ref) if pending_ref else None

    return render(request, "dashboard/key_detail.html", {
        "page_title": api_key.label or api_key.key_prefix + "...",
        "page_subtitle": api_key.environment.capitalize() + " API key",
        "api_key": api_key,
        "active_app": app,
        "related_keys": related_keys,
        "versions": services.get_key_versions(api_key),
        "audit_trail": services.get_key_audit_trail(api_key),
        "pending_key": pending_key,
        "pending_key_id": pending_key_id,
    })


@require_permission("keys.rotate")
def rotate_key(request, key_id):
    """Rotate an API key — create replacement, stay on detail page."""
    if request.method == "POST":
        app = services.get_active_app(request)
        if app:
            new_key, full_key, old_key = services.rotate_api_key(
                app, key_id, request=request,
            )
            request.session["pending_key"] = full_key
            request.session["pending_key_id"] = new_key.id
            return redirect("dashboard:key_detail", key_id=new_key.id)
    return redirect("dashboard:keys")


AUDIT_ACTION_CHOICES = [
    ("create", "create"),
    ("update", "update"),
    ("delete", "delete"),
    ("revoke", "revoke"),
    ("register", "register"),
    ("scope_create", "scope_create"),
    ("scope_modify", "scope_modify"),
    ("scope_dissolve", "scope_dissolve"),
    ("membership_change", "membership_change"),
    ("rule_change", "rule_change"),
    ("secret_create", "secret_create"),
    ("secret_ref_grant", "secret_ref_grant"),
    ("secret_revoke", "secret_revoke"),
]

AUDIT_TARGET_CHOICES = [
    ("api_key", "api_key"),
    ("application", "application"),
    ("role", "role"),
    ("principal", "principal"),
    ("scope", "scope"),
    ("secret", "secret"),
    ("secret_ref", "secret_ref"),
]


@require_permission("audit.view")
def audit(request):
    """Audit trail viewer — searchable log of all platform operations."""
    filters = {}
    for key in ("action", "target_type", "actor_id", "search", "since", "until"):
        val = request.GET.get(key, "").strip()
        if val:
            filters[key] = val

    page = int(request.GET.get("page", 1))
    entries = services.get_audit_trail(filters=filters, page=page)

    return render(request, "dashboard/audit.html", {
        "page_title": "Audit Trail",
        "page_subtitle": "Platform operations log",
        "entries": entries,
        "filters": filters,
        "action_choices": AUDIT_ACTION_CHOICES,
        "target_choices": AUDIT_TARGET_CHOICES,
        "current_page": page,
        "has_next": len(entries) == 25,
        "has_prev": page > 1,
    })


def getting_started(request):
    """Onboarding guide with step-by-step setup."""
    org = request.organization
    return render(request, "dashboard/getting_started.html", {
        "page_title": "Getting Started",
        "page_subtitle": "Set up your integration",
        "onboarding": services.get_onboarding_status(org) if org else None,
    })


def set_environment(request):
    """Set the active environment cookie."""
    env = request.POST.get("environment", "test")
    if env not in ("test", "live"):
        env = "test"
    referer = request.META.get("HTTP_REFERER", "/dashboard/")
    response = redirect(referer)
    response.set_cookie("scoped_env", env, max_age=60 * 60 * 24 * 365, samesite="Lax")
    return response


def set_application(request):
    """Set the active application cookie."""
    app_id = request.POST.get("application", "")
    referer = request.META.get("HTTP_REFERER", "/dashboard/")
    response = redirect(referer)
    if app_id:
        response.set_cookie("scoped_app", app_id, max_age=60 * 60 * 24 * 365, samesite="Lax")
    return response


@require_permission("members.view")
def members(request):
    """Organization member list."""
    org = request.organization
    memberships = (
        org.memberships
        .select_related("account", "role")
        .order_by("joined_at")
    ) if org else []
    return render(request, "dashboard/members.html", {
        "page_title": "Members",
        "page_subtitle": org.name if org else "",
        "memberships": memberships,
    })


@require_permission("keys.view")
def key_analytics(request):
    """API key analytics — lifecycle stats, recency, creation trends.

    Supports filtering via query params:
      ?app=all         — all applications in the org
      ?app=<id>        — specific application (default: active app)
      ?keys=id1,id2    — narrow to specific keys
    """
    org = request.organization
    active_app = services.get_active_app(request)

    # Parse filters from query params
    app_filter = request.GET.get("app", "")
    key_ids_raw = request.GET.get("keys", "")
    key_ids = [k.strip() for k in key_ids_raw.split(",") if k.strip()] or None

    if not app_filter and active_app:
        app_filter = active_app.id

    qs = analytics.resolve_key_queryset(org, app_id=app_filter, key_ids=key_ids)

    # Build filter context for the template
    filter_apps = org.applications.order_by("name") if org else []
    filterable_keys = analytics.get_filterable_keys(org) if org else []

    subtitle = "All applications" if app_filter == "all" else (
        active_app.name if active_app else "API key usage and lifecycle"
    )
    if key_ids:
        subtitle += f" ({len(key_ids)} keys selected)"

    return render(request, "dashboard/key_analytics.html", {
        "page_title": "Key Analytics",
        "page_subtitle": subtitle,
        "active_app": active_app,
        "lifecycle": analytics.get_key_lifecycle_stats(qs),
        "recency": analytics.to_json(analytics.get_key_recency_buckets(qs)),
        "creation_series": analytics.to_json(analytics.get_key_creation_series(qs)),
        "filter_app": app_filter,
        "filter_keys": key_ids or [],
        "filter_apps": filter_apps,
        "filterable_keys": filterable_keys,
    })


def sync(request):
    """Sync agent status — connection health, batch history, integrity."""
    org = request.organization
    page = int(request.GET.get("page", 1))
    return render(request, "dashboard/sync.html", {
        "page_title": "Sync Status",
        "page_subtitle": "Agent connection and batch history",
        "health": analytics.get_sync_health(org) if org else None,
        "integrity": analytics.get_chain_integrity(org) if org else None,
        "throughput": analytics.to_json(
            analytics.get_batch_throughput_series(org)
        ) if org else "null",
        "batches": analytics.get_batch_history(org, page=page) if org else [],
        "current_page": page,
    })
