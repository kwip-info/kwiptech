from django.urls import path
from . import views

urlpatterns = [
    path('usage', views.usage, name='market-usage'),
    path('checkout', views.checkout, name='market-checkout'),
    path('portal', views.portal, name='market-portal'),
    path('overage', views.configure_overage, name='market-overage'),
]
