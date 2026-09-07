from django.urls import path
from . import views
urlpatterns = [
    path('account', views.account),
    path('keys', views.keys),
    path('keys/<uuid:key_id>', views.revoke_key),
    path('device/start', views.device_start),
    path('device/poll', views.device_poll),
    path('device/approve', views.device_approval),
]
