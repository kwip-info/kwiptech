"""Public KWIP site, local admin, and explicit retired-service boundaries."""
from django.contrib import admin
from django.urls import include, path, re_path
from plane.retired import health, retired
urlpatterns = [
    path("healthz", health),
    path("v1/ping", health),
    re_path(r"^(?:v1|dashboard|webhooks|sign-in|sign-up)(?:/.*)?$", retired),
    path("admin/", admin.site.urls),
    path("", include("plane.public.urls")),
]
