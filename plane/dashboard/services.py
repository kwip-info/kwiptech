"""Dashboard service layer — data queries and key operations.

Key lifecycle operations use pyscoped's object system (dogfooding).
The scoped object is the authoritative record; the Django ApiKey
model is a projection for fast authentication lookups.
"""

from uuid import uuid4

from django.utils import timezone

from scoped.exceptions import ScopedError
from scoped.logging import get_logger

from plane.billing.models import UsageSnapshot
from plane.core.models import Account, ApiKey, Application, SyncBatchRecord, SyncedAuditEntry
from plane.dashboard.scoped import scoped_operation

KEY_PREFIX_LENGTH = 13  # "psc_live_" + 4 hex chars
SECRET_NAME_PREFIX = "api_key:"

logger = get_logger("plane.dashboard.services")


def get_active_env(request):
    """Read the active environment from the scoped_env cookie."""
    return request.COOKIES.get("scoped_env", "test")


def get_active_app(request):
    """Read the active application from the scoped_app cookie.

    Falls back to the default application for the current organization.
    Returns None if no organization is set.
    """
    org = getattr(request, "organization", None)
    if org is None:
        return None
    app_id = request.COOKIES.get("scoped_app")
    if app_id:
        try:
            return org.applications.get(id=app_id)
        except Application.DoesNotExist:
            pass
    return org.applications.filter(is_default=True).first()


def get_key_summary(application, environment):
    """Return key counts for the given environment."""
    qs = application.api_keys.filter(environment=environment)
    active = qs.filter(is_active=True).count()
    revoked = qs.filter(is_active=False).count()
    return {"active": active, "revoked": revoked, "total": active + revoked}


def get_keys(application, environment, show_revoked=False, page=1, per_page=25):
    """Return keys for the given environment, paginated.

    Default filters to active keys only. Pass show_revoked=True
    to include revoked keys.
    """
    from django.core.paginator import Paginator

    qs = application.api_keys.filter(environment=environment)
    if not show_revoked:
        qs = qs.filter(is_active=True)
    qs = qs.order_by("-created_at")

    paginator = Paginator(qs, per_page)
    return paginator.get_page(page)


def get_sync_status(organization, application=None, environment=None):
    """Return the latest sync info, or None if no syncs received."""
    from plane.dashboard.services_analytics import _account_ids_filtered
    account_ids = _account_ids_filtered(organization, application, environment)
    batch = (
        SyncBatchRecord.objects
        .filter(account_id__in=account_ids)
        .order_by("-received_at")
        .first()
    )
    if batch is None:
        return None
    total_entries = (
        SyncedAuditEntry.objects
        .filter(account_id__in=account_ids)
        .count()
    )
    return {
        "last_sync": batch.received_at,
        "total_entries": total_entries,
        "last_batch_count": batch.entry_count,
    }


def get_usage_summary(organization, application=None, environment=None):
    """Return the latest usage snapshot, or None."""
    from plane.dashboard.services_analytics import _account_ids_filtered
    account_ids = _account_ids_filtered(organization, application, environment)
    return (
        UsageSnapshot.objects
        .filter(account_id__in=account_ids)
        .order_by("-recorded_at")
        .first()
    )


def get_onboarding_status(organization):
    """Return onboarding completion status.

    Steps are sticky — once done, they stay done even if the
    resource is later removed. Onboarding is considered complete
    once usage data exists (meaning the full loop works).
    """
    has_key = ApiKey.objects.filter(
        application__organization=organization,
    ).exists()
    account_ids = list(
        organization.memberships.values_list("account_id", flat=True)
    )
    has_synced = SyncBatchRecord.objects.filter(account_id__in=account_ids).exists()
    has_usage = UsageSnapshot.objects.filter(account_id__in=account_ids).exists()
    return {
        "has_key": has_key,
        "has_synced": has_synced,
        "is_complete": has_usage,
    }


def create_api_key(account, application, environment, label="", request=None):
    """Create a new API key via scoped object + Django model.

    The scoped object records the lifecycle (versioned, audited).
    The Django model stores the key hash for fast auth lookups.
    The full key is encrypted at rest via scoped's secrets vault
    and a short-lived ref token is returned for one-time reveal.
    """
    full_key, key_hash = ApiKey.generate_key(environment)
    key_prefix = full_key[:KEY_PREFIX_LENGTH]
    key_id = uuid4().hex
    scoped_object_id = None
    secret_ref_token = None

    try:
        with scoped_operation() as client:
            obj, _version = client.objects.create(
                "api_key",
                data={
                    "key_id": key_id,
                    "key_prefix": key_prefix,
                    "environment": environment,
                    "label": label,
                    "is_active": True,
                },
            )
            scoped_object_id = obj.id

            secret, _sv = client.secrets.create(
                f"{SECRET_NAME_PREFIX}{key_id}",
                full_key,
                description=f"API key {key_prefix}... ({environment})",
            )

            from scoped.identity.context import ScopedContext
            principal = ScopedContext.current_or_none()
            if principal:
                ref = client.secrets.grant_ref(secret.id, principal.principal)
                secret_ref_token = ref.ref_token
    except Exception:  # Graceful degradation — scoped may be unavailable
        logger.warning("Scoped object/secret creation failed", key_id=key_id)

    api_key = ApiKey.objects.create(
        id=key_id,
        account=account,
        application=application,
        key_hash=key_hash,
        key_prefix=key_prefix,
        environment=environment,
        label=label,
        scoped_object_id=scoped_object_id,
    )

    reveal_value = secret_ref_token or full_key
    return api_key, reveal_value


def revoke_api_key(application, key_id, request=None):
    """Revoke an API key via scoped update + Django model update."""
    api_key = ApiKey.objects.get(id=key_id, application=application, is_active=True)
    now = timezone.now()

    # Update scoped object (dogfooding — creates new version + audit entry)
    if api_key.scoped_object_id:
        try:
            with scoped_operation() as client:
                client.objects.update(
                    api_key.scoped_object_id,
                    data={
                        "key_id": key_id,
                        "key_prefix": api_key.key_prefix,
                        "environment": api_key.environment,
                        "label": api_key.label,
                        "is_active": False,
                        "revoked_at": now.isoformat(),
                    },
                )
        except Exception:  # Graceful degradation — scoped may be unavailable
            logger.warning("Scoped object update failed", key_id=key_id)

    # Update Django model (projection)
    api_key.is_active = False
    api_key.revoked_at = now
    api_key.save(update_fields=["is_active", "revoked_at"])
    return api_key


def get_key_detail(application, key_id):
    """Return a single API key for the application, or None."""
    try:
        return ApiKey.objects.get(id=key_id, application=application)
    except ApiKey.DoesNotExist:
        return None


def get_related_keys(api_key):
    """Return all Django keys sharing the same scoped object (rotation chain)."""
    if not api_key.scoped_object_id:
        return [api_key]
    return list(
        ApiKey.objects
        .filter(scoped_object_id=api_key.scoped_object_id)
        .order_by("-created_at")
    )


def get_key_versions(api_key):
    """Return version history from scoped, or empty list."""
    if not api_key.scoped_object_id:
        return []
    try:
        from plane.dashboard.scoped import get_client
        client = get_client()
        return client.objects.versions(api_key.scoped_object_id)
    except Exception:  # Graceful degradation — scoped may be unavailable
        logger.warning("Failed to fetch versions", key_id=api_key.id)
        return []


def get_key_audit_trail(api_key):
    """Return the scoped audit trail for a key, most recent first."""
    if not api_key.scoped_object_id:
        return []
    try:
        from plane.dashboard.scoped import get_client
        client = get_client()
        return client.audit.query(
            target_id=api_key.scoped_object_id,
            order_by="-sequence",
        )
    except Exception:  # Graceful degradation — scoped may be unavailable
        logger.warning("Failed to fetch audit trail", key_id=api_key.id)
        return []


def get_audit_trail(
    organization, filters=None, page=1, per_page=25, sort="-sequence",
    application=None, environment=None,
):
    """Query synced audit entries with filters.

    Supported filters: action, target_type, actor_id, search, since, until.
    application/environment: narrow to entries from keys matching that app/env.
    sort: "sequence", "-sequence".
    Returns (entries, total_count) tuple.
    """
    from django.db.models import Q

    filters = filters or {}
    if organization is None:
        return [], 0

    # Start with all account IDs in the org
    account_ids = set(
        organization.memberships.values_list("account_id", flat=True)
    )

    # Narrow to accounts that have keys matching the app/env filter
    if application or environment:
        key_qs = ApiKey.objects.filter(account_id__in=account_ids)
        if application:
            key_qs = key_qs.filter(application=application)
        if environment:
            key_qs = key_qs.filter(environment=environment)
        account_ids = set(key_qs.values_list("account_id", flat=True))

    qs = SyncedAuditEntry.objects.filter(account_id__in=account_ids)

    # Apply filters
    if filters.get("action"):
        qs = qs.filter(action=filters["action"])
    if filters.get("target_type"):
        qs = qs.filter(target_type=filters["target_type"])
    if filters.get("actor_id"):
        qs = qs.filter(actor_id=filters["actor_id"])
    if filters.get("since"):
        from datetime import datetime as dt
        try:
            qs = qs.filter(timestamp__gte=dt.fromisoformat(filters["since"]))
        except ValueError:
            pass
    if filters.get("until"):
        from datetime import datetime as dt
        try:
            qs = qs.filter(timestamp__lte=dt.fromisoformat(filters["until"]))
        except ValueError:
            pass

    # Text search
    search = filters.get("search", "").strip()
    if search:
        qs = qs.filter(
            Q(action__icontains=search)
            | Q(target_type__icontains=search)
            | Q(target_id__icontains=search)
            | Q(actor_id__icontains=search)
        )

    # Sort
    if sort == "sequence":
        qs = qs.order_by("sequence", "account_id")
    else:
        qs = qs.order_by("-sequence", "account_id")

    total = qs.count()
    start = (page - 1) * per_page
    entries = list(qs[start:start + per_page])

    return entries, total


def resolve_key_secret(ref_token):
    """Resolve a secret ref token to get the plaintext API key.

    Returns the decrypted key string, or the ref_token as-is if
    it's already a plaintext key (fallback when vault isn't available).
    """
    if not ref_token:
        return None

    # If it looks like a raw key (fallback), return it directly
    if ref_token.startswith("psc_"):
        return ref_token

    try:
        with scoped_operation() as client:
            return client.secrets.resolve(ref_token)
    except Exception:  # Graceful degradation — scoped may be unavailable
        logger.warning("Failed to resolve secret ref")
        return None


def rotate_api_key(application, key_id, request=None):
    """Rotate a key: new credentials, same scoped object.

    The scoped object gets a new version (rotation event in the
    audit trail). A new Django ApiKey row is created for the new
    credentials. The old Django row is revoked. Both rows share
    the same scoped_object_id — one continuous lifecycle.

    Returns (new_api_key, reveal_value, old_api_key) tuple.
    """
    old_key = ApiKey.objects.get(id=key_id, application=application, is_active=True)
    now = timezone.now()

    # Generate new credentials
    full_key, key_hash = ApiKey.generate_key(old_key.environment)
    key_prefix = full_key[:KEY_PREFIX_LENGTH]
    new_key_id = uuid4().hex
    secret_ref_token = None

    # Update scoped object + store new key in vault
    if old_key.scoped_object_id:
        try:
            with scoped_operation() as client:
                client.objects.update(
                    old_key.scoped_object_id,
                    data={
                        "key_id": new_key_id,
                        "key_prefix": key_prefix,
                        "environment": old_key.environment,
                        "label": old_key.label,
                        "is_active": True,
                        "rotated_from": old_key.id,
                        "rotated_at": now.isoformat(),
                    },
                )

                # Store rotated key in vault
                secret, _sv = client.secrets.create(
                    f"{SECRET_NAME_PREFIX}{new_key_id}",
                    full_key,
                    description=f"Rotated API key {key_prefix}... ({old_key.environment})",
                )

                from scoped.identity.context import ScopedContext
                principal = ScopedContext.current_or_none()
                if principal:
                    ref = client.secrets.grant_ref(secret.id, principal.principal)
                    secret_ref_token = ref.ref_token
        except Exception:  # Graceful degradation — scoped may be unavailable
            logger.warning("Scoped rotation failed", key_id=key_id)

    # Revoke old Django model
    old_key.is_active = False
    old_key.revoked_at = now
    old_key.save(update_fields=["is_active", "revoked_at"])

    # Create new Django model pointing to same scoped object
    new_key = ApiKey.objects.create(
        id=new_key_id,
        account=old_key.account,
        application=old_key.application,
        key_hash=key_hash,
        key_prefix=key_prefix,
        environment=old_key.environment,
        label=old_key.label,
        scoped_object_id=old_key.scoped_object_id,
    )

    reveal_value = secret_ref_token or full_key
    return new_key, reveal_value, old_key
