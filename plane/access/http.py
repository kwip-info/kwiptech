import json
from functools import wraps
from django.core.exceptions import ValidationError, RequestDataTooBig
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .errors import Problem
from .auth import authenticate, client_peer, rate_limit

def body_json(request, max_bytes=1048576):
    if request.content_type != 'application/json':
        raise Problem('unsupported_media_type', 'Use Content-Type: application/json.', 415)
    try:
        if int(request.META.get('CONTENT_LENGTH') or 0) > max_bytes:
            raise Problem('body_too_large', 'The request exceeds the allowed batch size.', 413)
        body = request.read(max_bytes + 1)
        if len(body) > max_bytes:
            raise Problem('body_too_large', 'The request exceeds the allowed batch size.', 413)
        result = json.loads(body, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite number')))
        if not isinstance(result, dict):
            raise ValueError('Expected object')
        return result
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
        raise Problem('invalid_json', 'Send a valid JSON object.') from exc

def endpoint(methods=('GET',), authenticated=True):
    def decorate(view):
        @csrf_exempt
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            try:
                if request.method not in methods:
                    raise Problem('method_not_allowed', 'Method not supported.', 405)
                rate_limit('api-peer:' + client_peer(request), 300)
                principal = authenticate(request) if authenticated else None
                response = view(request, principal, *args, **kwargs)
                if not hasattr(response, 'status_code'):
                    response = JsonResponse(response)
            except Problem as exc:
                response = JsonResponse({'error': {'code': exc.code, 'message': exc.message, **exc.details}}, status=exc.status)
                if exc.status == 429:
                    response['Retry-After'] = str(exc.details.get('retry_after', 60))
                if exc.status == 401:
                    response['WWW-Authenticate'] = 'Bearer'
                if exc.status == 405:
                    response['Allow'] = ', '.join(methods)
            except RequestDataTooBig:
                response = JsonResponse({'error': {'code': 'body_too_large', 'message': 'The request is too large.'}}, status=413)
            except ValidationError as exc:
                response = JsonResponse({'error': {'code': 'validation_error', 'message': '; '.join(exc.messages)}}, status=400)
            response['Cache-Control'] = 'no-store'
            response['X-Content-Type-Options'] = 'nosniff'
            return response
        return wrapped
    return decorate
