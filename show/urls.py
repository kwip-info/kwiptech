from functools import lru_cache
import json
from pathlib import Path
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render
from django.urls import path, re_path
from django.views.decorators.http import require_safe
from plane.public.cutover import moved

@require_safe
def home(request):
    return render(request, 'show/index.html')

@lru_cache(maxsize=1)
def catalog():
    return json.loads((Path(__file__).parent / 'data/catalog.json').read_text())

@require_safe
def content(request):
    response = JsonResponse(catalog())
    response['Cache-Control'] = 'public, max-age=3600'
    return response

@require_safe
def health(request):
    return JsonResponse({'status': 'ok', 'service': 'kwip-slides', 'catalog_items': len(catalog()['items']), 'marketplace': 'retired'})

def retired(request):
    return JsonResponse({'error': 'service_retired', 'message': 'The KWIP data marketplace and hosted PyScoped service have been retired.'}, status=410)


@require_safe
def content_info(request):
    return render(request, 'show/content.html', {'count': len(catalog()['items'])})

urlpatterns = [path('about/content', content_info), path('', home), path('api/slides/catalog', content), path('healthz', health),
    path('robots.txt', lambda r: HttpResponse('User-agent: *\nAllow: /\nDisallow: /api/\n', content_type='text/plain')),
    re_path(r'^(?:api/v2|v1|dashboard|webhooks|payments|integrations|account|explore|sign-in|sign-up|agents.txt)(?:/.*)?$', retired),
    path('<path:path>', moved)]
