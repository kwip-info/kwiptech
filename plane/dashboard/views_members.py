"""Member override management — add, edit, remove app+env role overrides."""

from uuid import uuid4

from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect

from plane.core.models import AppMembership, Application, Membership, Role
from plane.dashboard.views import require_permission


@require_permission("members.manage")
def add_override(request, membership_id):
    """Add an app+env role override for a member."""
    org = request.organization
    if org is None:
        raise Http404

    membership = get_object_or_404(Membership, id=membership_id, organization=org)

    if request.method != "POST":
        return redirect("dashboard:members")

    app_id = request.POST.get("application")
    env = request.POST.get("environment") or None
    role_id = request.POST.get("role")

    app = get_object_or_404(Application, id=app_id, organization=org)
    role = get_object_or_404(Role, id=role_id, organization=org)

    if env and env not in ("test", "live"):
        env = None

    if AppMembership.objects.filter(
        membership=membership, application=app, environment=env,
    ).exists():
        messages.error(request, "An override already exists for this scope.")
        return redirect("dashboard:members")

    override = AppMembership.objects.create(
        id=uuid4().hex,
        membership=membership,
        application=app,
        environment=env,
        role=role,
    )
    override.sync_to_scoped()

    env_label = (env or "all envs").capitalize()
    messages.success(
        request,
        f"{membership.account} is now {role.name} on {app.name} / {env_label}.",
    )
    return redirect("dashboard:members")


@require_permission("members.manage")
def edit_override(request, override_id):
    """Change the role on an existing override."""
    org = request.organization
    if org is None:
        raise Http404

    override = get_object_or_404(
        AppMembership, id=override_id, membership__organization=org,
    )

    if request.method != "POST":
        return redirect("dashboard:members")

    role_id = request.POST.get("role")
    role = get_object_or_404(Role, id=role_id, organization=org)

    override.revoke_in_scoped()
    override.role = role
    override.save(update_fields=["role"])
    override.sync_to_scoped()

    messages.success(request, f"Override updated to {role.name}.")
    return redirect("dashboard:members")


@require_permission("members.manage")
def remove_override(request, override_id):
    """Remove an app+env role override (reverts to org-level role)."""
    org = request.organization
    if org is None:
        raise Http404

    override = get_object_or_404(
        AppMembership, id=override_id, membership__organization=org,
    )

    if request.method != "POST":
        return redirect("dashboard:members")

    override.revoke_in_scoped()
    override.delete()
    messages.success(request, "Override removed. Member reverted to org-level role.")
    return redirect("dashboard:members")
