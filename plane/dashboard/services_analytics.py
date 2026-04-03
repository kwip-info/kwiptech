"""Analytics service functions — chart data, trends, sync health.

All functions return JSON-serializable data ready for ApexCharts.
Date series use ISO date strings as labels. Counts are plain integers.
"""

import json
from collections import defaultdict
from datetime import timedelta

from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from scoped.exceptions import ScopedError
from scoped.logging import get_logger

from plane.billing.models import UsageSnapshot
from plane.core.models import ApiKey, SyncBatchRecord, SyncedAuditEntry

logger = get_logger("plane.dashboard.analytics")


def _date_range(days):
    """Return (start_date, [date_str, ...]) for the last N days."""
    today = timezone.now().date()
    start = today - timedelta(days=days - 1)
    labels = [(start + timedelta(days=i)).isoformat() for i in range(days)]
    return start, labels


def _account_ids_for_org(organization):
    return list(organization.memberships.values_list("account_id", flat=True))


def _account_ids_filtered(organization, application=None, environment=None):
    """Account IDs narrowed by app/env via API key lookup."""
    all_ids = set(organization.memberships.values_list("account_id", flat=True))
    if not application and not environment:
        return list(all_ids)
    key_qs = ApiKey.objects.filter(account_id__in=all_ids)
    if application:
        key_qs = key_qs.filter(application=application)
    if environment:
        key_qs = key_qs.filter(environment=environment)
    return list(key_qs.values_list("account_id", flat=True).distinct())


# -- Dashboard home --------------------------------------------------------

def get_recent_activity(organization, limit=10, application=None, environment=None):
    """Last N synced audit entries for the activity feed (most recent first)."""
    if organization is None:
        return []
    account_ids = _account_ids_filtered(organization, application, environment)
    return list(
        SyncedAuditEntry.objects
        .filter(account_id__in=account_ids)
        .order_by("-received_at")[:limit]
    )


def get_audit_count_today(organization, application=None, environment=None):
    """Total synced audit entries received today."""
    if organization is None:
        return 0
    account_ids = _account_ids_filtered(organization, application, environment)
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        SyncedAuditEntry.objects
        .filter(account_id__in=account_ids, received_at__gte=today_start)
        .count()
    )


def get_env_breakdown(application):
    """Test vs live active key counts for doughnut chart."""
    if application is None:
        return {"test": 0, "live": 0}
    qs = application.api_keys.filter(is_active=True)
    counts = qs.values("environment").annotate(count=Count("id"))
    result = {"test": 0, "live": 0}
    for row in counts:
        result[row["environment"]] = row["count"]
    return result


def get_activity_series(organization, days=7, application=None, environment=None):
    """Daily operation counts from synced audit entries.

    Shows all SDK activity synced to the platform, grouped by day.
    """
    start, labels = _date_range(days)
    data = {label: 0 for label in labels}

    if organization is None:
        return {"labels": labels, "data": [data[d] for d in labels]}

    account_ids = _account_ids_filtered(organization, application, environment)
    rows = (
        SyncedAuditEntry.objects
        .filter(account_id__in=account_ids, received_at__date__gte=start)
        .annotate(day=TruncDate("received_at"))
        .values("day")
        .annotate(count=Count("id"))
    )
    for row in rows:
        day_str = row["day"].isoformat()
        if day_str in data:
            data[day_str] = row["count"]

    return {"labels": labels, "data": [data[d] for d in labels]}


# -- Key analytics ---------------------------------------------------------

def resolve_key_queryset(organization, app_id=None, key_ids=None, environment=None):
    """Build an ApiKey queryset from filter params.

    app_id="all" or None → all keys across the org.
    app_id=<id>          → keys for that specific application.
    key_ids=[id, ...]    → further narrow to specific keys.
    environment="test"|"live"|None → filter by environment.
    """
    if app_id and app_id != "all":
        qs = ApiKey.objects.filter(
            application_id=app_id,
            application__organization=organization,
        )
    else:
        qs = ApiKey.objects.filter(application__organization=organization)

    if environment:
        qs = qs.filter(environment=environment)

    if key_ids:
        qs = qs.filter(id__in=key_ids)

    return qs


def get_filterable_keys(organization):
    """Return all keys for the org, grouped by app, for the filter UI."""
    from plane.core.models import Application
    apps = Application.objects.filter(organization=organization).order_by("name")
    result = []
    for app in apps:
        keys = list(
            app.api_keys
            .order_by("-created_at")
            .values("id", "key_prefix", "label", "environment", "is_active")[:50]
        )
        result.append({"app": app, "keys": keys})
    return result


def get_key_lifecycle_stats(qs):
    """Total, active, revoked counts + average key age."""
    total = qs.count()
    active = qs.filter(is_active=True).count()
    revoked = total - active

    avg_age_days = 0
    active_keys = qs.filter(is_active=True)
    if active_keys.exists():
        now = timezone.now()
        ages = [(now - k.created_at).days for k in active_keys]
        avg_age_days = sum(ages) // len(ages) if ages else 0

    return {
        "total": total,
        "active": active,
        "revoked": revoked,
        "avg_age_days": avg_age_days,
    }


def get_key_recency_buckets(qs):
    """Group active keys by last_used_at recency."""
    bucket_labels = [
        "Last hour", "Last 24h", "Last 7 days",
        "Last 30 days", "30+ days", "Never",
    ]
    now = timezone.now()

    counts = defaultdict(int)
    for key in qs.filter(is_active=True):
        if key.last_used_at is None:
            counts["Never"] += 1
        elif (now - key.last_used_at) < timedelta(hours=1):
            counts["Last hour"] += 1
        elif (now - key.last_used_at) < timedelta(hours=24):
            counts["Last 24h"] += 1
        elif (now - key.last_used_at) < timedelta(days=7):
            counts["Last 7 days"] += 1
        elif (now - key.last_used_at) < timedelta(days=30):
            counts["Last 30 days"] += 1
        else:
            counts["30+ days"] += 1

    data = [counts.get(label, 0) for label in bucket_labels]
    return {"labels": bucket_labels, "data": data}


def get_key_creation_series(qs, days=30):
    """Daily key creation counts."""
    start, labels = _date_range(days)
    data = {label: 0 for label in labels}

    rows = (
        qs.filter(created_at__date__gte=start)
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(count=Count("id"))
    )
    for row in rows:
        day_str = row["day"].isoformat()
        if day_str in data:
            data[day_str] = row["count"]

    return {"labels": labels, "data": [data[d] for d in labels]}


# -- Sync status -----------------------------------------------------------

def get_sync_health(organization, application=None, environment=None):
    """Connection status, last batch details, SDK version."""
    account_ids = _account_ids_filtered(organization, application, environment)
    batch = (
        SyncBatchRecord.objects
        .filter(account_id__in=account_ids)
        .order_by("-received_at")
        .first()
    )
    if batch is None:
        return {
            "status": "disconnected",
            "last_sync": None,
            "sdk_version": None,
            "total_entries": 0,
            "last_sequence": 0,
        }

    now = timezone.now()
    age = now - batch.received_at
    if age < timedelta(hours=1):
        status = "connected"
    elif age < timedelta(hours=24):
        status = "idle"
    else:
        status = "disconnected"

    total_entries = (
        SyncedAuditEntry.objects
        .filter(account_id__in=account_ids)
        .count()
    )

    return {
        "status": status,
        "last_sync": batch.received_at,
        "sdk_version": batch.sdk_version,
        "total_entries": total_entries,
        "last_sequence": batch.last_sequence,
    }


def get_batch_throughput_series(organization, days=30, application=None, environment=None):
    """Daily batch entry counts for throughput line chart."""
    start, labels = _date_range(days)
    account_ids = _account_ids_filtered(organization, application, environment)

    data = {label: 0 for label in labels}
    rows = (
        SyncBatchRecord.objects
        .filter(account_id__in=account_ids, received_at__date__gte=start)
        .annotate(day=TruncDate("received_at"))
        .values("day")
        .annotate(total_entries=Count("id"), total_count=Count("entry_count"))
    )
    for row in rows:
        day_str = row["day"].isoformat()
        if day_str in data:
            data[day_str] = row["total_entries"]

    return {"labels": labels, "data": [data[d] for d in labels]}


def get_batch_history(organization, page=1, per_page=25, application=None, environment=None):
    """Paginated batch records, most recent first."""
    account_ids = _account_ids_filtered(organization, application, environment)
    qs = (
        SyncBatchRecord.objects
        .filter(account_id__in=account_ids)
        .order_by("-received_at")
    )
    paginator = Paginator(qs, per_page)
    return paginator.get_page(page)


def get_chain_integrity(organization, application=None, environment=None):
    """Check sequence continuity in synced audit entries."""
    account_ids = _account_ids_filtered(organization, application, environment)
    entries = (
        SyncedAuditEntry.objects
        .filter(account_id__in=account_ids)
        .order_by("sequence")
        .values_list("sequence", flat=True)
    )
    sequences = list(entries[:1000])
    if not sequences:
        return {"verified": True, "total": 0, "message": "No entries to verify"}

    gaps = []
    for i in range(1, len(sequences)):
        if sequences[i] != sequences[i - 1] + 1:
            gaps.append(sequences[i - 1] + 1)
            if len(gaps) >= 5:
                break

    if gaps:
        return {
            "verified": False,
            "total": len(sequences),
            "first_gap": gaps[0],
            "message": f"Gap detected at sequence {gaps[0]}",
        }
    return {
        "verified": True,
        "total": len(sequences),
        "message": f"Chain verified: {len(sequences)} entries, no gaps",
    }


# -- Usage trends ----------------------------------------------------------

def get_resource_trend_series(organization, days=30, application=None, environment=None):
    """Daily UsageSnapshot values for area chart."""
    start, labels = _date_range(days)
    account_ids = _account_ids_filtered(organization, application, environment)

    objects_data = {label: 0 for label in labels}
    principals_data = {label: 0 for label in labels}
    scopes_data = {label: 0 for label in labels}

    snapshots = (
        UsageSnapshot.objects
        .filter(account_id__in=account_ids, recorded_at__date__gte=start)
        .order_by("recorded_at")
    )
    for snap in snapshots:
        day_str = snap.recorded_at.date().isoformat()
        if day_str in objects_data:
            objects_data[day_str] = snap.active_objects
            principals_data[day_str] = snap.active_principals
            scopes_data[day_str] = snap.active_scopes

    return {
        "labels": labels,
        "objects": [objects_data[d] for d in labels],
        "principals": [principals_data[d] for d in labels],
        "scopes": [scopes_data[d] for d in labels],
    }


def get_audit_volume_series(organization, days=30, application=None, environment=None):
    """Daily synced audit entry counts for bar chart."""
    start, labels = _date_range(days)
    account_ids = _account_ids_filtered(organization, application, environment)

    data = {label: 0 for label in labels}
    rows = (
        SyncedAuditEntry.objects
        .filter(account_id__in=account_ids, received_at__date__gte=start)
        .annotate(day=TruncDate("received_at"))
        .values("day")
        .annotate(count=Count("id"))
    )
    for row in rows:
        day_str = row["day"].isoformat()
        if day_str in data:
            data[day_str] = row["count"]

    return {"labels": labels, "data": [data[d] for d in labels]}


# -- JSON helpers ----------------------------------------------------------

def to_json(data):
    """Serialize data for embedding in template script tags."""
    return json.dumps(data)
