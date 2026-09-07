"""Public KWIP site, local admin, and explicit retired-service boundaries."""
from django.contrib import admin
from django.urls import include, path, re_path
from plane.retired import health, retired
from plane.commerce.views import webhook as market_stripe_webhook
from plane.access.webhooks import clerk_webhook
from plane.exports.views import jobs as market_exports
urlpatterns = [
    path("api/v2/exports", market_exports),
    path("api/v2/exports/", include("plane.exports.urls")),
    path("api/v2/billing/", include("plane.commerce.urls")),
    path("integrations/clerk", clerk_webhook),
    path("integrations/stripe", market_stripe_webhook),
    path("api/v2/", include("plane.access.urls")),
    path("healthz", health),
    path("v1/ping", health),
    re_path(r"^(?:v1|dashboard|webhooks|sign-in|sign-up)(?:/.*)?$", retired),
    path("admin/", admin.site.urls),
    path("", include("plane.market.urls")),
    path("", include("plane.public.urls")),
]
