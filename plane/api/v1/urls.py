"""V1 API URL configuration."""

from django.urls import path

from plane.api.v1 import views

urlpatterns = [
    # Health
    path("ping", views.ping),

    # Sync
    path("sync/batch", views.ingest_batch),
    path("sync/verify", views.verify_sync),

    # Keys
    path("keys", views.list_keys),
    path("keys/create", views.create_key),
    path("keys/revoke", views.revoke_key),

    # Usage
    path("usage", views.get_usage),
    path("plan", views.get_plan),
]
