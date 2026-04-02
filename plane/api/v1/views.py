"""V1 API views — sync ingest, key management, usage, health.

All views authenticate via API key (see ``plane.api.auth``).
Request/response validation uses the pyscoped contract models
from ``scoped.sync.models``.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone

from django.utils import timezone as dj_timezone
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from plane.api.throttles import SyncBatchThrottle, KeyCreateThrottle

from plane.core.models import Account, ApiKey, SyncBatchRecord, SyncedAuditEntry
from plane.billing.models import BillingPeriod, UsageSnapshot

from scoped.sync.models import (
    SyncBatch,
    SyncBatchAck,
    SyncVerifyRequest,
    SyncVerifyResponse,
    PingResponse,
    CreateKeyRequest,
    CreateKeyResponse,
    ListKeysResponse,
    ApiKeyMetadata,
    RevokeKeyRequest,
    RevokeKeyResponse,
    ApiEnvironment,
)


# =========================================================================
# HMAC Signature Verification
# =========================================================================


def _verify_signature(request, api_key):
    """Verify HMAC-SHA256 signature on sync batch.

    The SDK signs each batch body with a key derived from the raw API key:
      signing_key = SHA256(raw_key + ":pyscoped-sync-v1")

    The platform stores that derived key in ``api_key.signing_key_hash``
    at key-creation time, so it can recompute the HMAC without ever
    storing the raw key.

    Legacy keys (created before signing was added) have a null
    ``signing_key_hash`` — we skip verification for those to avoid
    breaking existing integrations.
    """
    signature = request.META.get("HTTP_X_PYSCOPED_SIGNATURE")
    if not signature:
        return False  # No signature provided

    if not api_key.signing_key_hash:
        return True  # Legacy key without signing_key — skip verification

    # Recompute HMAC over raw request body
    body = request.body
    expected = hmac.new(
        api_key.signing_key_hash.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(signature, expected)


# =========================================================================
# Health
# =========================================================================

@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def ping(request):
    """Health check — no auth required."""
    resp = PingResponse(
        ok=True,
        server_time=datetime.now(timezone.utc),
        api_version="2026-04-01",
    )
    return Response(resp.model_dump(mode="json"))


# =========================================================================
# Sync
# =========================================================================

@api_view(["POST"])
@throttle_classes([SyncBatchThrottle])
def ingest_batch(request):
    """Receive a sync batch from the SDK agent.

    Validates the batch, verifies the HMAC signature, stores audit
    entries, and updates usage snapshots.
    """
    account: Account = request.user
    api_key: ApiKey = request.auth

    # Verify HMAC signature before any processing
    if not _verify_signature(request, api_key):
        return Response({"error": "Invalid signature"}, status=status.HTTP_401_UNAUTHORIZED)

    try:
        batch = SyncBatch.model_validate(request.data)
    except Exception as exc:
        return Response(
            {"error": "validation_error", "message": str(exc), "details": {}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Billing status enforcement
    org = account.personal_organization
    if org and org.billing_status == "suspended":
        ack = SyncBatchAck(
            batch_id=batch.batch_id,
            accepted=False,
            server_sequence=0,
            server_chain_hash="",
            message="Account suspended — update payment method to resume sync",
            errors=["billing_suspended"],
        )
        return Response(ack.model_dump(mode="json"), status=status.HTTP_402_PAYMENT_REQUIRED)

    # Plan limit enforcement
    if org:
        from plane.billing.models import Plan as PlanModel
        plan_obj = PlanModel.objects.filter(id=org.plan).first()
        if plan_obj:
            counts = batch.resource_counts
            errors = []

            if plan_obj.overage_per_object_cents == 0:
                # Free tier — hard limits, no overage allowed
                if counts.active_objects > plan_obj.max_objects:
                    errors.append(
                        f"Object limit exceeded: {counts.active_objects}/{plan_obj.max_objects}"
                    )
                if counts.active_principals > plan_obj.max_principals:
                    errors.append(
                        f"Principal limit exceeded: {counts.active_principals}/{plan_obj.max_principals}"
                    )
            else:
                # Paid tier — hard ceiling at 10x max to prevent bill shock
                hard_object_cap = plan_obj.max_objects * 10
                hard_principal_cap = plan_obj.max_principals * 10
                if counts.active_objects > hard_object_cap:
                    errors.append(
                        f"Object hard cap exceeded: {counts.active_objects}/{hard_object_cap} — contact support to increase"
                    )
                if counts.active_principals > hard_principal_cap:
                    errors.append(
                        f"Principal hard cap exceeded: {counts.active_principals}/{hard_principal_cap} — contact support to increase"
                    )

            if errors:
                ack = SyncBatchAck(
                    batch_id=batch.batch_id,
                    accepted=False,
                    server_sequence=0,
                    server_chain_hash="",
                    message="Plan limits exceeded",
                    errors=errors,
                )
                return Response(ack.model_dump(mode="json"), status=status.HTTP_402_PAYMENT_REQUIRED)

        # Sync interval enforcement
        if plan_obj:
            last_batch = (
                SyncBatchRecord.objects
                .filter(account=account)
                .order_by("-received_at")
                .first()
            )
            if last_batch:
                from django.utils import timezone
                elapsed = (timezone.now() - last_batch.received_at).total_seconds()
                if elapsed < plan_obj.min_sync_interval_seconds:
                    ack = SyncBatchAck(
                        batch_id=batch.batch_id,
                        accepted=False,
                        server_sequence=last_batch.last_sequence,
                        server_chain_hash=last_batch.chain_hash,
                        message=f"Sync interval not met: {int(elapsed)}s/{plan_obj.min_sync_interval_seconds}s",
                    )
                    return Response(ack.model_dump(mode="json"), status=status.HTTP_429_TOO_MANY_REQUESTS)

    # Deduplication — check if we've already received this batch
    if SyncBatchRecord.objects.filter(id=batch.batch_id).exists():
        ack = SyncBatchAck(
            batch_id=batch.batch_id,
            accepted=True,
            server_sequence=batch.last_sequence,
            server_chain_hash=batch.chain_hash,
            message="duplicate batch (already received)",
        )
        return Response(ack.model_dump(mode="json"))

    # Store audit entries
    entries_to_create = []
    for entry in batch.entries:
        entries_to_create.append(
            SyncedAuditEntry(
                id=entry.id,
                account=account,
                sequence=entry.sequence,
                actor_id=entry.actor_id,
                action=entry.action,
                target_type=entry.target_type,
                target_id=entry.target_id,
                timestamp=entry.timestamp,
                hash=entry.hash,
                previous_hash=entry.previous_hash,
                scope_id=entry.scope_id,
                parent_trace_id=entry.parent_trace_id,
                metadata_json=entry.metadata,
                batch_id=batch.batch_id,
            )
        )

    # Bulk create, ignoring duplicates (sequence is unique per account)
    SyncedAuditEntry.objects.bulk_create(
        entries_to_create, ignore_conflicts=True
    )

    # Record the batch
    SyncBatchRecord.objects.create(
        id=batch.batch_id,
        account=account,
        first_sequence=batch.first_sequence,
        last_sequence=batch.last_sequence,
        chain_hash=batch.chain_hash,
        content_hash=batch.content_hash,
        signature=batch.signature,
        entry_count=len(batch.entries),
        sdk_version=batch.sdk_version,
    )

    # Record usage snapshot
    counts = batch.resource_counts
    UsageSnapshot.objects.create(
        account=account,
        active_objects=counts.active_objects,
        active_principals=counts.active_principals,
        active_scopes=counts.active_scopes,
        audit_entries_synced=len(batch.entries),
    )

    # Update peak usage for current billing period
    _update_peak_usage(account, counts.active_objects, counts.active_principals, len(batch.entries))

    ack = SyncBatchAck(
        batch_id=batch.batch_id,
        accepted=True,
        server_sequence=batch.last_sequence,
        server_chain_hash=batch.chain_hash,
        message=f"accepted {len(batch.entries)} entries",
    )
    return Response(ack.model_dump(mode="json"), status=status.HTTP_201_CREATED)


@api_view(["POST"])
def verify_sync(request):
    """Verify chain integrity between SDK and server."""
    account: Account = request.user

    try:
        req = SyncVerifyRequest.model_validate(request.data)
    except Exception as exc:
        return Response(
            {"error": "validation_error", "message": str(exc), "details": {}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Get server-side chain state
    latest_entry = (
        SyncedAuditEntry.objects
        .filter(account=account)
        .order_by("-sequence")
        .first()
    )

    server_count = SyncedAuditEntry.objects.filter(account=account).count()
    server_hash = latest_entry.hash if latest_entry else ""
    server_seq = latest_entry.sequence if latest_entry else 0

    verified = (
        req.local_chain_hash == server_hash
        and req.local_entry_count == server_count
    )

    resp = SyncVerifyResponse(
        verified=verified,
        local_chain_hash=req.local_chain_hash,
        server_chain_hash=server_hash,
        local_entry_count=req.local_entry_count,
        server_entry_count=server_count,
        first_mismatch_sequence=None if verified else (server_seq + 1),
        message="chains match" if verified else "chain mismatch detected",
    )
    return Response(resp.model_dump(mode="json"))


# =========================================================================
# Key Management
# =========================================================================

@api_view(["GET"])
def list_keys(request):
    """List all API keys for the authenticated account."""
    account: Account = request.user
    keys = ApiKey.objects.filter(account=account).order_by("-created_at")

    resp = ListKeysResponse(
        keys=[
            ApiKeyMetadata(
                key_id=k.id,
                key_prefix=k.key_prefix,
                environment=ApiEnvironment(k.environment),
                label=k.label,
                is_active=k.is_active,
                created_at=k.created_at,
                last_used_at=k.last_used_at,
            )
            for k in keys
        ]
    )
    return Response(resp.model_dump(mode="json"))


@api_view(["POST"])
@throttle_classes([KeyCreateThrottle])
def create_key(request):
    """Create a new API key (synced to pyscoped for audit trail)."""
    account: Account = request.user

    try:
        req = CreateKeyRequest.model_validate(request.data)
    except Exception as exc:
        return Response(
            {"error": "validation_error", "message": str(exc), "details": {}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    import uuid

    full_key, key_hash = ApiKey.generate_key(req.environment.value)
    key_id = uuid.uuid4().hex
    scoped_object_id = None

    # Dogfooding: create scoped object for audit trail + versioning
    try:
        from plane.dashboard.scoped import scoped_operation
        with scoped_operation() as client:
            obj, _ver = client.objects.create(
                "api_key",
                data={
                    "key_id": key_id,
                    "key_prefix": full_key[:13],
                    "environment": req.environment.value,
                    "label": req.label,
                    "is_active": True,
                },
            )
            scoped_object_id = obj.id
    except Exception:
        pass  # Scoped is additive — Django model is the projection

    # Derive and store the signing key for HMAC verification on future syncs
    signing_key = hashlib.sha256(
        (full_key + ":pyscoped-sync-v1").encode()
    ).hexdigest()

    ApiKey.objects.create(
        id=key_id,
        account=account,
        key_hash=key_hash,
        signing_key_hash=signing_key,
        key_prefix=full_key[:13],
        environment=req.environment.value,
        label=req.label,
        scoped_object_id=scoped_object_id,
    )

    resp = CreateKeyResponse(
        key_id=key_id,
        api_key=full_key,
        environment=req.environment,
        created_at=dj_timezone.now(),
    )
    return Response(resp.model_dump(mode="json"), status=status.HTTP_201_CREATED)


@api_view(["POST"])
def revoke_key(request):
    """Revoke an API key."""
    account: Account = request.user

    try:
        req = RevokeKeyRequest.model_validate(request.data)
    except Exception as exc:
        return Response(
            {"error": "validation_error", "message": str(exc), "details": {}},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        key = ApiKey.objects.get(id=req.key_id, account=account)
    except ApiKey.DoesNotExist:
        return Response(
            {"error": "not_found", "message": "Key not found", "details": {}},
            status=status.HTTP_404_NOT_FOUND,
        )

    # Dogfooding: update scoped object for audit trail
    if key.scoped_object_id:
        try:
            from plane.dashboard.scoped import scoped_operation
            with scoped_operation() as client:
                client.objects.update(
                    key.scoped_object_id,
                    data={
                        "key_id": key.id,
                        "key_prefix": key.key_prefix,
                        "environment": key.environment,
                        "label": key.label,
                        "is_active": False,
                        "revoked_at": dj_timezone.now().isoformat(),
                    },
                )
        except Exception:
            pass  # Scoped is additive

    now = dj_timezone.now()
    key.is_active = False
    key.revoked_at = now
    key.save(update_fields=["is_active", "revoked_at"])

    resp = RevokeKeyResponse(key_id=req.key_id, revoked_at=now)
    return Response(resp.model_dump(mode="json"))


# =========================================================================
# Usage & Billing
# =========================================================================

@api_view(["GET"])
def get_usage(request):
    """Get current billing period usage."""
    account: Account = request.user

    period = (
        BillingPeriod.objects
        .filter(account=account, finalized=False)
        .order_by("-period_start")
        .first()
    )

    if period is None:
        return Response({"error": "no_billing_period", "message": "No active billing period", "details": {}})

    latest_snapshot = (
        UsageSnapshot.objects
        .filter(account=account)
        .order_by("-recorded_at")
        .first()
    )

    data = {
        "period_start": period.period_start.isoformat(),
        "period_end": period.period_end.isoformat(),
        "peak_objects": period.peak_objects,
        "peak_principals": period.peak_principals,
        "current_objects": latest_snapshot.active_objects if latest_snapshot else 0,
        "current_principals": latest_snapshot.active_principals if latest_snapshot else 0,
        "audit_entries_synced": period.total_audit_entries,
        "last_sync_at": latest_snapshot.recorded_at.isoformat() if latest_snapshot else None,
    }
    return Response(data)


@api_view(["GET"])
def get_plan(request):
    """Get current plan details from the Plan model."""
    account: Account = request.user
    org = account.personal_organization
    plan_id = org.plan if org else "free"

    from plane.billing.models import Plan
    plan_obj = Plan.objects.filter(id=plan_id).first()

    if plan_obj:
        limits = {
            "max_objects": plan_obj.max_objects,
            "max_principals": plan_obj.max_principals,
            "audit_retention_days": plan_obj.audit_retention_days,
            "min_sync_interval_seconds": plan_obj.min_sync_interval_seconds,
            "tier": plan_obj.id,
        }
        overage_allowed = plan_obj.overage_per_object_cents > 0
    else:
        limits = {
            "max_objects": 1000,
            "max_principals": 50,
            "audit_retention_days": 7,
            "min_sync_interval_seconds": 3600,
            "tier": "free",
        }
        overage_allowed = False

    return Response({
        "plan": plan_id,
        "limits": limits,
        "overage_allowed": overage_allowed,
    })


# =========================================================================
# Helpers
# =========================================================================

def _update_peak_usage(account: Account, objects: int, principals: int, entries: int):
    """Update peak counts for the current billing period.

    Uses atomic F() expressions and conditional updates to avoid
    read-modify-write race conditions under concurrent sync requests.
    """
    from django.db.models import F, Value
    from django.db.models.functions import Greatest

    from plane.billing.tasks import ensure_billing_period

    org = account.personal_organization
    if org:
        period = ensure_billing_period(org, account)
    else:
        period = (
            BillingPeriod.objects
            .filter(account=account, finalized=False)
            .order_by("-period_start")
            .first()
        )
    if period is None:
        return

    BillingPeriod.objects.filter(id=period.id).update(
        peak_objects=Greatest(F("peak_objects"), Value(objects)),
        peak_principals=Greatest(F("peak_principals"), Value(principals)),
        total_audit_entries=F("total_audit_entries") + entries,
    )
