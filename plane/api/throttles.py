"""Custom DRF throttle classes for API rate limiting."""

from rest_framework.throttling import UserRateThrottle


class SyncBatchThrottle(UserRateThrottle):
    """Rate limit for sync batch ingestion.

    Uses the 'sync' scope defined in REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'].
    """

    scope = "sync"


class KeyCreateThrottle(UserRateThrottle):
    """Rate limit for API key creation.

    Uses the 'key_create' scope defined in REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'].
    """

    scope = "key_create"
