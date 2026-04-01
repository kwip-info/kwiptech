"""Public page URL configuration."""

from django.urls import path

from plane.public import views

app_name = "public"

urlpatterns = [
    path("", views.landing, name="landing"),
    path("pricing", views.pricing, name="pricing"),
    path("status", views.status, name="status"),
    path("security", views.security, name="security"),
    path("terms", views.terms, name="terms"),
    path("privacy", views.privacy, name="privacy"),
    path("cookies", views.cookies, name="cookies"),
    path("docs", views.docs, name="docs"),
    path("sign-in", views.sign_in, name="sign_in"),
    path("sign-up", views.sign_up, name="sign_up"),
    path("sign-in/<path:rest>", views.sign_in, name="sign_in_step"),
    path("sign-up/<path:rest>", views.sign_up, name="sign_up_step"),
]
