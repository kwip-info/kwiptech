"""Neutral public surface and explicit, body-free legacy information redirects."""
from django.http import Http404, HttpResponse, HttpResponsePermanentRedirect, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_safe

BASE = 'https://kwip.info/technology/'
DESTINATIONS = {name: BASE + name + '/' for name in ('digest', 'pricing', 'status', 'security', 'terms', 'privacy', 'cookies')}
DESTINATIONS.update({'docs': BASE + 'pyscoped/docs/', 'docs/manifest.json': BASE + 'pyscoped/docs/manifest.json', 'llms.txt': BASE + 'llms.txt'})
for name in ('adoption', 'guarantees', 'migration'):
    DESTINATIONS['docs/' + name + '.md'] = BASE + 'pyscoped/docs/' + name + '/'
    DESTINATIONS['docs/raw/' + name + '.md'] = BASE + 'pyscoped/docs/raw/' + name + '.md'
for name in ('AGENTS', 'CLAUDE'):
    DESTINATIONS['docs/' + name.lower() + '.md'] = BASE + 'pyscoped/docs/raw/' + name + '.md'
    DESTINATIONS['docs/raw/' + name + '.md'] = BASE + 'pyscoped/docs/raw/' + name + '.md'
DESTINATIONS.update({
    'docs/platform/digest-runtime.md': BASE + 'digest/docs/',
    'docs/platform/raw/digest-runtime.md': BASE + 'digest/docs/raw/digest-runtime.md',
    'docs/platform/manifest.json': BASE + 'digest/docs/manifest.json',
})

@require_safe
def landing(request):
    return render(request, 'public/neutral.html')

@require_safe
def robots(request):
    return HttpResponse('User-agent: *\nAllow: /\nDisallow: /admin/\nSitemap: https://kwip.info/sitemap.xml\n', content_type='text/plain')

@csrf_exempt
def moved(request, path):
    destination = DESTINATIONS.get(path.rstrip('/'))
    if destination is None:
        raise Http404
    if request.method not in ('GET', 'HEAD'):
        response = JsonResponse({'error': 'information_moved', 'message': 'This endpoint no longer accepts submissions. Visit the new page to submit an inquiry.', 'destination': destination}, status=410)
        response['Cache-Control'] = 'no-store'
        return response
    return HttpResponsePermanentRedirect(destination)
