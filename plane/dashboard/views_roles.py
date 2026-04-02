"""Role management views — list, create, edit, delete."""

from uuid import uuid4

from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from plane.core.models import Permission, Role, RolePermission
from plane.dashboard.views import require_permission


def _actor(request):
    account = getattr(request, "clerk_user", None)
    return account.id if account else "system"


@require_permission("roles.view")
def roles(request):
    """Role list page — shows all roles for the current organization."""
    org = request.organization
    role_list = (
        org.roles
        .prefetch_related("permissions")
        .order_by("-is_default", "name")
    ) if org else []

    return render(request, "dashboard/roles.html", {
        "page_title": "Roles",
        "page_subtitle": "Manage access control",
        "roles": role_list,
    })


@require_permission("roles.manage")
def role_editor(request, role_id=None):
    """Create or edit a role with permission matrix."""
    org = request.organization
    if org is None:
        raise Http404

    role = None
    if role_id:
        role = get_object_or_404(Role, id=role_id, organization=org)
        if role.is_default:
            messages.error(request, "Default roles cannot be edited.")
            return redirect("dashboard:roles")

    all_permissions = Permission.objects.all()
    categories = _group_permissions(all_permissions)

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        if not name:
            messages.error(request, "Role name is required.")
            return render(request, "dashboard/role_editor.html", {
                "page_title": "New Role" if role is None else role.name,
                "page_subtitle": "Edit permissions",
                "role": role,
                "categories": categories,
                "selected_perms": set(request.POST.getlist("permissions")),
            })

        selected_ids = set(request.POST.getlist("permissions"))
        actor = _actor(request)

        if role is None:
            role = Role.objects.create(
                id=uuid4().hex,
                organization=org,
                name=name,
            )

        else:
            role.name = name
            role.save(update_fields=["name"])

        RolePermission.objects.filter(role=role).delete()
        perms = Permission.objects.filter(id__in=selected_ids)
        RolePermission.objects.bulk_create([
            RolePermission(role=role, permission=p) for p in perms
        ])

        role.sync_rules_to_scoped(created_by=actor)

        messages.success(request, f"Role \"{role.name}\" saved.")
        return redirect("dashboard:roles")

    selected_perms = set()
    if role:
        selected_perms = set(role.permissions.values_list("id", flat=True))

    return render(request, "dashboard/role_editor.html", {
        "page_title": role.name if role else "New Role",
        "page_subtitle": "Edit permissions",
        "role": role,
        "categories": categories,
        "selected_perms": selected_perms,
    })


@require_permission("roles.manage")
def role_delete(request, role_id):
    """Delete a custom role — blocked for defaults or roles with members."""
    org = request.organization
    role = get_object_or_404(Role, id=role_id, organization=org)

    if role.is_default:
        messages.error(request, "Default roles cannot be deleted.")
        return redirect("dashboard:roles")

    if role.memberships.exists():
        messages.error(
            request,
            f"Role \"{role.name}\" has active members. Reassign them first.",
        )
        return redirect("dashboard:roles")

    if request.method == "POST":
        name = role.name
        role.archive_rules_in_scoped(archived_by=_actor(request))
        role.delete()
        messages.success(request, f"Role \"{name}\" deleted.")

    return redirect("dashboard:roles")


def _group_permissions(permissions):
    """Group permissions by category for the matrix UI."""
    groups = {}
    for perm in permissions:
        groups.setdefault(perm.category, []).append(perm)
    return groups
