from django.urls import path

from plane.billing import views

app_name = "billing"

urlpatterns = [
    path("checkout/", views.create_checkout_session, name="checkout"),
    path("success/", views.checkout_success, name="checkout_success"),
    path("portal/", views.customer_portal, name="portal"),
]
