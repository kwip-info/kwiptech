from django.urls import path
from . import views

urlpatterns = [
    path('<uuid:job_id>', views.detail),
    path('<uuid:job_id>/download', views.artifact),
]
