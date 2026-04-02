"""Test URL configuration."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("v1/", include("plane.api.v1.urls")),
    path("webhooks/", include("plane.webhooks.urls")),
    path("dashboard/", include("plane.dashboard.urls")),
    path("", include("plane.public.urls")),
]
