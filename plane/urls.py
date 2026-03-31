"""URL configuration for pyscoped management plane."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("v1/", include("plane.api.v1.urls")),
]
