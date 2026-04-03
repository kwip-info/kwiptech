"""Dashboard URL configuration."""

from django.urls import path

from plane.billing import views as billing_views
from plane.dashboard import views, views_apps, views_members, views_roles

app_name = "dashboard"

urlpatterns = [
    path("", views.index, name="index"),
    path("keys/", views.keys, name="keys"),
    path("keys/analytics/", views.key_analytics, name="key_analytics"),
    path("keys/<str:key_id>/", views.key_detail, name="key_detail"),
    path("keys/<str:key_id>/revoke/", views.revoke_key, name="revoke_key"),
    path("keys/<str:key_id>/rotate/", views.rotate_key, name="rotate_key"),
    path("audit/", views.audit, name="audit"),
    path("sync/", views.sync, name="sync"),
    path("members/", views.members, name="members"),
    path("members/<str:membership_id>/overrides/add/", views_members.add_override, name="member_override_add"),
    path("members/overrides/<str:override_id>/edit/", views_members.edit_override, name="member_override_edit"),
    path("members/overrides/<str:override_id>/remove/", views_members.remove_override, name="member_override_remove"),
    path("apps/", views_apps.applications, name="applications"),
    path("apps/new/", views_apps.create_application, name="app_create"),
    path("apps/<str:app_id>/edit/", views_apps.edit_application, name="app_edit"),
    path("apps/<str:app_id>/delete/", views_apps.delete_application, name="app_delete"),
    path("roles/", views_roles.roles, name="roles"),
    path("roles/new/", views_roles.role_editor, name="role_create"),
    path("roles/<str:role_id>/", views_roles.role_editor, name="role_editor"),
    path("roles/<str:role_id>/delete/", views_roles.role_delete, name="role_delete"),
    path("billing/", billing_views.billing_overview, name="billing"),
    path("billing/checkout/", billing_views.create_checkout_session, name="billing_checkout"),
    path("billing/success/", billing_views.checkout_success, name="billing_success"),
    path("billing/portal/", billing_views.customer_portal, name="billing_portal"),
    path("getting-started/", views.getting_started, name="getting_started"),
    path("set-env/", views.set_environment, name="set_env"),
    path("set-app/", views.set_application, name="set_app"),
]
