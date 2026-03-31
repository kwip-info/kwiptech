"""Custom DRF exception handler returning ApiError format."""

from __future__ import annotations

from rest_framework.views import exception_handler
from rest_framework.response import Response


def api_exception_handler(exc, context):
    """Return errors in the standard ApiError envelope."""
    response = exception_handler(exc, context)

    if response is not None:
        error_code = getattr(exc, "default_code", "error")
        response.data = {
            "error": error_code,
            "message": str(exc.detail) if hasattr(exc, "detail") else str(exc),
            "details": {},
        }

    return response
