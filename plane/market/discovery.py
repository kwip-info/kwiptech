"""Static, public agent documentation; never fetch a remote specification."""
import json
from functools import lru_cache
from pathlib import Path

from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_safe

DOCUMENTS = Path(__file__).resolve().parents[2] / 'docs' / 'marketplace'


@lru_cache(maxsize=1)
def specification():
    return json.loads((DOCUMENTS / 'openapi.json').read_text(encoding='utf-8'))


def public_headers(response):
    response['Cache-Control'] = 'public, max-age=300'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@require_safe
def openapi(request):
    return public_headers(JsonResponse(specification()))


@require_safe
def agents(request):
    return public_headers(HttpResponse(
        (DOCUMENTS / 'AGENT_GUIDE.md').read_text(encoding='utf-8'),
        content_type='text/plain; charset=utf-8',
    ))
