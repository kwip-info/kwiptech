from django.urls import path

from plane.webhooks import views

app_name = "webhooks"

urlpatterns = [
    path("clerk/", views.clerk_webhook, name="clerk"),
]
