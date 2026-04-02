"""Simple in-process rate limiter for plain Django views.

This is defense-in-depth for the Clerk webhook endpoint — Svix signature
verification is the primary protection. The limiter uses a per-IP sliding
window stored in a module-level dict (suitable for single-process /
gunicorn pre-fork deployments; shared state is not required because
webhook traffic is low-volume).
"""

import functools
import time
from collections import defaultdict

from django.http import HttpResponse


def webhook_rate_limit(max_requests: int = 60, window_seconds: int = 60):
    """Decorator that rate-limits a Django view by client IP.

    Returns HTTP 429 when the threshold is exceeded.
    """
    # ip -> list of timestamps (pruned on each request)
    _buckets: dict[str, list[float]] = defaultdict(list)

    def decorator(view_func):
        @functools.wraps(view_func)
        def wrapper(request, *args, **kwargs):
            ip = _get_client_ip(request)
            now = time.monotonic()
            cutoff = now - window_seconds

            # Prune expired entries
            bucket = _buckets[ip]
            _buckets[ip] = bucket = [t for t in bucket if t > cutoff]

            if len(bucket) >= max_requests:
                return HttpResponse("Rate limit exceeded", status=429)

            bucket.append(now)
            return view_func(request, *args, **kwargs)

        return wrapper
    return decorator


def _get_client_ip(request) -> str:
    """Extract client IP, respecting X-Forwarded-For behind a proxy."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")
