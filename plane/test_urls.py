"""Test URL configuration — excludes v1 API which requires scoped package."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("webhooks/", include("plane.webhooks.urls")),
    path("dashboard/", include("plane.dashboard.urls")),
    path("", include("plane.public.urls")),
]
