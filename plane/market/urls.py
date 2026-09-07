from django.urls import path
from . import views, discovery
urlpatterns = [
    path('api/v2/openapi.json', discovery.openapi),
    path('agents.txt', discovery.agents),
    path('', views.page),
    path('data/<slug:slug>', views.page, {'screen': 'dataset'}),
    path('api/v2/plans', views.plans),
    path('marketplace/privacy', views.policy, {'kind': 'privacy'}),
    path('marketplace/terms', views.policy, {'kind': 'terms'}),
    path('plans', views.page, {'screen': 'plans'}),
    path('developers', views.page, {'screen': 'developers'}),
    path('account', views.page, {'screen': 'account'}),
    path('account/connect', views.page, {'screen': 'connect'}),
    path('account/sign-in', views.page, {'screen': 'signin'}),
    path('api/v2/datasets', views.datasets),
    path('api/v2/datasets/<slug:slug>', views.dataset_detail),
    path('api/v2/datasets/<slug:slug>/query', views.query_dataset),
    path('api/v2/operator/datasets', views.register),
    path('api/v2/operator/datasets/<slug:slug>/sources', views.source_register),
    path('api/v2/operator/datasets/<slug:slug>/sources/<slug:source_slug>/batches', views.ingest),
]
