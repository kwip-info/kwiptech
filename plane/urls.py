"""URL configuration for pyscoped management plane."""

from django.contrib import admin
from django.urls import include, path

from plane.billing import webhooks as billing_webhooks

urlpatterns = [
    path("admin/", admin.site.urls),
    path("v1/", include("plane.api.v1.urls")),
    path("webhooks/", include("plane.webhooks.urls")),
    path("webhooks/stripe/", billing_webhooks.stripe_webhook, name="stripe_webhook"),
    path("dashboard/", include("plane.dashboard.urls")),
    path("", include("plane.public.urls")),
]
