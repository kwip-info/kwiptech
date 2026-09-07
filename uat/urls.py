import jwt
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.urls import path
from django.utils import timezone
from plane.urls import urlpatterns as production_urls


def session(request):
    actor = request.COOKIES.get('uat_actor', 'free')
    if actor not in ('free', 'pro', 'operator'):
        return JsonResponse({'token': None})
    now = int(timezone.now().timestamp())
    return JsonResponse({'token': jwt.encode({'sub': 'user_uat_' + actor, 'sid': 'sess_uat', 'iss': settings.MARKET_CLERK_ISSUER,
        'azp': settings.MARKET_ORIGIN, 'iat': now, 'nbf': now, 'exp': now + 60}, settings.UAT_PRIVATE_KEY, algorithm='RS256')})


def clerk(request):
    script = '''
const actor=(document.cookie.match(/(?:^|; )uat_actor=([^;]*)/)||[])[1]||'free';
window.Clerk={load:async()=>{},user:actor==='signedout'?null:{firstName:'Synthetic UAT'},
session:actor==='signedout'?null:{getToken:async()=>{const r=await fetch('/_uat/session');return (await r.json()).token;}},
signOut:async()=>{document.cookie='uat_actor=signedout;path=/;SameSite=Strict';location.href='/account/sign-in';},
mountSignIn:el=>{el.innerHTML='<p>Synthetic browser identity. No real provider or account.</p>'+['free','pro','operator'].map(a=>'<button type="button" data-uat="'+a+'">Sign in as '+a+'</button>').join(' ');el.querySelectorAll('[data-uat]').forEach(b=>b.onclick=()=>{document.cookie='uat_actor='+b.dataset.uat+';path=/;SameSite=Strict';location.href='/account';});}};
const showBanner=()=>{const banner=document.createElement('div');banner.textContent='SYNTHETIC UAT · local fixtures · no real data or payments';banner.style.cssText='background:#f3dfa6;padding:8px;text-align:center;font:12px system-ui';document.body.prepend(banner);};if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',showBanner);else showBanner();
'''
    return HttpResponse(script, content_type='application/javascript')

urlpatterns = [path('_uat/session', session), path('npm/@clerk/ui@1/dist/ui.browser.js', lambda request: HttpResponse('/* Synthetic UI shim */', content_type='application/javascript')), path('npm/@clerk/clerk-js@6/dist/clerk.browser.js', clerk)] + production_urls

# Deliberate local failure injection: discard one successful query response after
# the production handler commits, proving browser retries reuse the receipt.
from threading import Lock
from plane.market.views import query_dataset
from django.views.decorators.csrf import csrf_exempt
_fault_lock = Lock()
_fault_armed = False
@csrf_exempt
def arm_fault(request):
    global _fault_armed
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    with _fault_lock:
        _fault_armed = True
    return JsonResponse({'armed': True})
@csrf_exempt
def fault_query(request, slug):
    global _fault_armed
    response = query_dataset(request, slug)
    with _fault_lock:
        if _fault_armed and response.status_code == 200:
            _fault_armed = False
            return HttpResponse('Synthetic response lost after commit', status=503)
    return response
urlpatterns = [path('_uat/fault', arm_fault), path('api/v2/datasets/<slug:slug>/query', fault_query)] + urlpatterns

# A real 390px child browsing context for responsive UAT when the host browser
# cannot resize its outer window. Its CSS media queries use the frame viewport.
def mobile(request):
    return HttpResponse('<!doctype html><html><head><title>390px responsive UAT</title></head><body style="margin:0;background:#ddd"><p style="font:14px system-ui;padding:12px">Synthetic responsive UAT · 390 × 844 CSS pixels</p><iframe title="Mobile marketplace" src="/" width="390" height="844" style="border:1px solid #777;display:block;margin:0 20px"></iframe></body></html>')
urlpatterns = [path('_uat/mobile', mobile)] + urlpatterns
