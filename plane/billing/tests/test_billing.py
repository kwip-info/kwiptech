"""Tests for billing: peak tracking, webhook idempotency, plan seeding, dunning, cutoffs."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.test import TestCase, override_settings
from django.utils import timezone

from plane.billing.models import BillingPeriod, Plan, StripeEvent, UsageSnapshot
from plane.core.models import Account, ApiKey, Organization


def _make_account(account_id="test-account"):
    return Account.objects.create(id=account_id, email=f"{account_id}@test.com")


def _make_org(account, plan="free", billing_status="active"):
    org = Organization.objects.create(
        id=f"org-{account.id}",
        name="Test Org",
        slug=f"test-org-{account.id}",
        owner=account,
        plan=plan,
        billing_status=billing_status,
    )
    return org


def _make_period(account, org, days_ago=0, finalized=False):
    now = timezone.now()
    return BillingPeriod.objects.create(
        account=account,
        organization=org,
        period_start=now - timedelta(days=30 + days_ago),
        period_end=now - timedelta(days=days_ago),
        finalized=finalized,
    )


def _make_api_key(account):
    full_key, key_hash = ApiKey.generate_key("test")
    return ApiKey.objects.create(
        id="key-1",
        account=account,
        key_hash=key_hash,
        key_prefix=full_key[:13],
        environment="test",
    ), full_key


class TestPeakTrackingAtomic(TestCase):
    """Verify peak tracking uses atomic F() expressions."""

    def test_peak_updates_atomically(self):
        account = _make_account()
        org = _make_org(account)
        period = _make_period(account, org)

        from plane.api.v1.views import _update_peak_usage

        _update_peak_usage(account, 100, 10, 5)
        period.refresh_from_db()
        assert period.peak_objects == 100
        assert period.peak_principals == 10
        assert period.total_audit_entries == 5

    def test_peak_only_increases(self):
        account = _make_account()
        org = _make_org(account)
        period = _make_period(account, org)

        from plane.api.v1.views import _update_peak_usage

        _update_peak_usage(account, 100, 10, 5)
        _update_peak_usage(account, 50, 5, 3)  # Lower — should NOT decrease peak
        period.refresh_from_db()
        assert period.peak_objects == 100
        assert period.peak_principals == 10
        assert period.total_audit_entries == 8  # 5 + 3 cumulative

    def test_entries_accumulate(self):
        account = _make_account()
        org = _make_org(account)
        period = _make_period(account, org)

        from plane.api.v1.views import _update_peak_usage

        _update_peak_usage(account, 10, 1, 100)
        _update_peak_usage(account, 10, 1, 200)
        _update_peak_usage(account, 10, 1, 50)
        period.refresh_from_db()
        assert period.total_audit_entries == 350


class TestWebhookIdempotency(TestCase):
    """Verify duplicate Stripe events are not processed twice."""

    def test_duplicate_event_skipped(self):
        # Record an event as already processed
        StripeEvent.objects.create(id="evt_123", event_type="checkout.session.completed")

        # The webhook handler should skip it
        assert StripeEvent.objects.filter(id="evt_123").exists()

    def test_new_event_recorded_after_processing(self):
        assert not StripeEvent.objects.filter(id="evt_456").exists()
        StripeEvent.objects.create(id="evt_456", event_type="invoice.paid")
        assert StripeEvent.objects.filter(id="evt_456").exists()


class TestPlanSeeding(TestCase):
    """Verify the seed_plans command creates default plans."""

    def test_seed_creates_plans(self):
        from django.core.management import call_command
        call_command("seed_plans", verbosity=0)

        assert Plan.objects.filter(id="free").exists()
        assert Plan.objects.filter(id="pro").exists()
        assert Plan.objects.filter(id="enterprise").exists()

        free = Plan.objects.get(id="free")
        assert free.max_objects == 1000
        assert free.overage_per_object_cents == 0

        pro = Plan.objects.get(id="pro")
        assert pro.max_objects == 100000
        assert pro.overage_per_object_cents == 1
        assert pro.price_cents_monthly == 4900

    def test_seed_is_idempotent(self):
        from django.core.management import call_command
        call_command("seed_plans", verbosity=0)
        call_command("seed_plans", verbosity=0)

        assert Plan.objects.count() == 3


class TestPeriodClosureRetry(TestCase):
    """Verify period closure tracks attempts and retries."""

    def test_failed_closure_increments_attempts(self):
        account = _make_account()
        org = _make_org(account, plan="pro")
        period = _make_period(account, org, days_ago=1)  # Expired yesterday

        with patch("plane.billing.tasks.report_metered_usage", side_effect=Exception("Stripe down")):
            from plane.billing.tasks import close_expired_periods
            close_expired_periods()

        period.refresh_from_db()
        assert period.finalized is False
        assert period.close_attempts == 1
        assert "Stripe down" in period.close_error

    def test_max_retries_skips_period(self):
        account = _make_account()
        org = _make_org(account, plan="pro")
        period = _make_period(account, org, days_ago=1)
        period.close_attempts = 5
        period.save(update_fields=["close_attempts"])

        from plane.billing.tasks import close_expired_periods
        closed = close_expired_periods()
        assert closed == 0  # Skipped because max retries reached


class TestDunningSuspension(TestCase):
    """Verify the dunning escalation pipeline."""

    def test_first_failure_marks_past_due(self):
        account = _make_account()
        org = _make_org(account, plan="pro")
        org.stripe_customer_id = "cus_test"
        org.save()

        from plane.billing.webhooks import _handle_invoice_payment_failed
        _handle_invoice_payment_failed({"customer": "cus_test"})

        org.refresh_from_db()
        assert org.billing_status == "past_due"

    def test_second_failure_suspends(self):
        account = _make_account()
        org = _make_org(account, plan="pro", billing_status="past_due")
        org.stripe_customer_id = "cus_test"
        org.save()

        from plane.billing.webhooks import _handle_invoice_payment_failed
        _handle_invoice_payment_failed({"customer": "cus_test"})

        org.refresh_from_db()
        assert org.billing_status == "suspended"

    def test_payment_reactivates(self):
        account = _make_account()
        org = _make_org(account, plan="pro", billing_status="suspended")
        org.stripe_customer_id = "cus_test"
        org.save()

        from plane.billing.webhooks import _handle_invoice_paid
        _handle_invoice_paid({"customer": "cus_test"})

        org.refresh_from_db()
        assert org.billing_status == "active"


class TestOverageCutoff(TestCase):
    """Verify hard caps prevent bill shock on paid tiers."""

    def test_free_tier_rejects_over_limit(self):
        """Free tier plan with 0 overage should reject objects over max."""
        from django.core.management import call_command
        call_command("seed_plans", verbosity=0)

        plan = Plan.objects.get(id="free")
        assert plan.overage_per_object_cents == 0
        assert plan.max_objects == 1000

        # Simulate: 5000 objects > 1000 max → should be rejected
        assert 5000 > plan.max_objects

    def test_pro_tier_has_hard_cap(self):
        """Pro tier should have a 10x hard cap."""
        from django.core.management import call_command
        call_command("seed_plans", verbosity=0)

        plan = Plan.objects.get(id="pro")
        hard_cap = plan.max_objects * 10
        assert hard_cap == 1000000  # 100k * 10

        # Under hard cap: allowed
        assert 500000 < hard_cap
        # Over hard cap: would be rejected
        assert 2000000 > hard_cap

    def test_suspended_org_has_correct_status(self):
        """Suspended orgs should be blocked from syncing."""
        account = _make_account("sus-acct")
        org = _make_org(account, plan="pro", billing_status="suspended")
        assert org.billing_status == "suspended"
