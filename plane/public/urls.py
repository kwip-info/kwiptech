"""Public information has moved; only the preparation page remains here."""
from django.urls import path
from plane.public import cutover

app_name = 'public'
urlpatterns = [
    path('', cutover.landing, name='landing'),
    path('robots.txt', cutover.robots, name='robots_txt'),
    path('<path:path>', cutover.moved, name='moved'),
]
