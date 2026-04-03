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
    filt = {"application": app, "environment": env}

    ctx = {
        "page_title": "Dashboard",
        "page_subtitle": f"{app.name} \u00b7 {env.capitalize()}" if app else "Overview",
        "active_env": env,
        "active_app": app,
        "sync_status": services.get_sync_status(org, **filt) if org else None,
        "usage_summary": services.get_usage_summary(org, **filt) if org else None,
        "onboarding": services.get_onboarding_status(org) if org else None,
        "recent_activity": analytics.get_recent_activity(org, **filt) if org else [],
        "audit_count_today": analytics.get_audit_count_today(org, **filt) if org else 0,
        "activity_series": analytics.to_json(
            analytics.get_activity_series(org, **filt)
        ),
        "resource_trends": analytics.to_json(
            analytics.get_resource_trend_series(org, **filt)
        ) if org else "null",
        "audit_volume": analytics.to_json(
            analytics.get_audit_volume_series(org, **filt)
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


def _audit_choices(organization):
    """Build action and target_type choices from actual synced data."""
    from plane.core.models import SyncedAuditEntry

    if organization is None:
        return [], []

    account_ids = list(
        organization.memberships.values_list("account_id", flat=True)
    )
    qs = SyncedAuditEntry.objects.filter(account_id__in=account_ids)

    actions = sorted(
        qs.values_list("action", flat=True).distinct()
    )
    targets = sorted(
        qs.values_list("target_type", flat=True).distinct()
    )
    return (
        [(a, a) for a in actions],
        [(t, t) for t in targets],
    )


@require_permission("audit.view")
def audit(request):
    """Audit trail viewer — searchable log of all platform operations."""
    filters = {}
    for key in ("action", "target_type", "actor_id", "search", "since", "until"):
        val = request.GET.get(key, "").strip()
        if val:
            filters[key] = val

    org = request.organization
    app = services.get_active_app(request)
    env = services.get_active_env(request)
    page = int(request.GET.get("page", 1))
    sort = request.GET.get("sort", "-sequence")
    if sort not in ("sequence", "-sequence"):
        sort = "-sequence"
    per_page = 25

    entries, total = services.get_audit_trail(
        org, filters=filters, page=page, sort=sort, per_page=per_page,
        application=app, environment=env,
    )
    action_choices, target_choices = _audit_choices(org)

    total_pages = max(1, (total + per_page - 1) // per_page)
    # Build visible page numbers: current +/- 2, always include 1 and last
    visible_pages = sorted({
        p for p in [1, page - 2, page - 1, page, page + 1, page + 2, total_pages]
        if 1 <= p <= total_pages
    })

    subtitle = "Platform operations log"
    if app:
        subtitle = f"{app.name} \u00b7 {env.capitalize()}"

    return render(request, "dashboard/audit.html", {
        "page_title": "Audit Trail",
        "page_subtitle": subtitle,
        "active_app": app,
        "active_env": env,
        "entries": entries,
        "filters": filters,
        "action_choices": action_choices,
        "target_choices": target_choices,
        "current_page": page,
        "current_sort": sort,
        "total": total,
        "total_pages": total_pages,
        "visible_pages": visible_pages,
    })


def getting_started(request):
    """Onboarding guide with step-by-step setup."""
    org = request.organization
    return render(request, "dashboard/getting_started.html", {
        "page_title": "Getting Started",
        "page_subtitle": "Set up your integration",
        "hide_toggles": True,
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
    """Organization member list with app+env role overrides."""
    org = request.organization
    memberships = (
        org.memberships
        .select_related("account", "role")
        .prefetch_related(
            "app_memberships__application",
            "app_memberships__role",
        )
        .order_by("joined_at")
    ) if org else []
    apps = org.applications.order_by("name") if org else []
    roles = org.roles.order_by("-is_default", "name") if org else []
    return render(request, "dashboard/members.html", {
        "page_title": "Members",
        "page_subtitle": org.name if org else "",
        "hide_toggles": True,
        "memberships": memberships,
        "apps": apps,
        "roles": roles,
    })


@require_permission("keys.view")
def key_analytics(request):
    """API key analytics — lifecycle stats, recency, creation trends.

    Uses global app/env toggles. Optional query param:
      ?keys=id1,id2    — narrow to specific keys
    """
    org = request.organization
    active_app = services.get_active_app(request)
    env = services.get_active_env(request)

    # Optional key filter
    key_ids_raw = request.GET.get("keys", "")
    key_ids = [k.strip() for k in key_ids_raw.split(",") if k.strip()] or None

    qs = analytics.resolve_key_queryset(
        org, app_id=active_app.id if active_app else None,
        key_ids=key_ids, environment=env,
    )

    # Key picker data (scoped to active app + env)
    filterable_keys = []
    if active_app:
        keys = list(
            active_app.api_keys
            .filter(environment=env)
            .order_by("-created_at")
            .values("id", "key_prefix", "label", "environment", "is_active")[:50]
        )
        filterable_keys = [{"app": active_app, "keys": keys}]

    subtitle = f"{active_app.name} \u00b7 {env.capitalize()}" if active_app else "All keys"
    if key_ids:
        subtitle += f" ({len(key_ids)} keys selected)"

    return render(request, "dashboard/key_analytics.html", {
        "page_title": "Key Analytics",
        "page_subtitle": subtitle,
        "active_app": active_app,
        "active_env": env,
        "lifecycle": analytics.get_key_lifecycle_stats(qs),
        "recency": analytics.to_json(analytics.get_key_recency_buckets(qs)),
        "creation_series": analytics.to_json(analytics.get_key_creation_series(qs)),
        "filter_keys": key_ids or [],
        "filterable_keys": filterable_keys,
    })


def sync(request):
    """Sync agent status — connection health, batch history, integrity."""
    org = request.organization
    app = services.get_active_app(request)
    env = services.get_active_env(request)
    page = int(request.GET.get("page", 1))

    filt = {"application": app, "environment": env}
    subtitle = f"{app.name} \u00b7 {env.capitalize()}" if app else "Agent connection and batch history"

    return render(request, "dashboard/sync.html", {
        "page_title": "Sync Status",
        "page_subtitle": subtitle,
        "active_app": app,
        "active_env": env,
        "health": analytics.get_sync_health(org, **filt) if org else None,
        "integrity": analytics.get_chain_integrity(org, **filt) if org else None,
        "throughput": analytics.to_json(
            analytics.get_batch_throughput_series(org, **filt)
        ) if org else "null",
        "batches": analytics.get_batch_history(org, page=page, **filt) if org else [],
        "current_page": page,
    })
