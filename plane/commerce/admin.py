"""Superuser-only financial diagnostics; never a billing mutation interface."""
from django.contrib import admin
from .models import BillingAccount, BillingConsent, Delivery, MeterOutbox, MeterReconciliation, StripeEvent


class BillingDiagnosticAdmin(admin.ModelAdmin):
    actions = None
    list_per_page = 50
    show_full_result_count = False
    sensitive_fields = ()

    def has_module_permission(self, request):
        return self.has_view_permission(request)

    def has_view_permission(self, request, obj=None):
        return bool(request.user.is_active and request.user.is_staff and request.user.is_superuser)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return self.fields

    def get_queryset(self, request):
        return super().get_queryset(request).defer(*self.sensitive_fields)


@admin.register(BillingAccount)
class BillingAccountAdmin(BillingDiagnosticAdmin):
    fields = ('workspace', 'stripe_customer_id', 'stripe_subscription_id', 'status', 'period_start', 'period_end', 'allowance_start', 'overage_enabled', 'spend_cap_cents', 'metered_item_active', 'checkout_expires_at', 'reconciled_at', 'cancellation_requested_at', 'cancellation_completed_at')
    list_display = ('workspace', 'status', 'overage_enabled', 'spend_cap_cents', 'period_end', 'reconciled_at')
    list_filter = ('status', 'overage_enabled', 'metered_item_active')
    search_fields = ('=workspace__id', '=stripe_customer_id', '=stripe_subscription_id')
    sensitive_fields = ('checkout_url', 'checkout_generation', 'checkout_session_id')


@admin.register(Delivery)
class DeliveryAdmin(BillingDiagnosticAdmin):
    fields = ('id', 'workspace', 'dataset_slug', 'request_id', 'fingerprint', 'records', 'credits', 'overage_credits', 'pricing_cents_per_10000', 'period_start', 'period_end', 'created_at')
    list_display = ('id', 'workspace', 'dataset_slug', 'records', 'credits', 'overage_credits', 'created_at')
    list_filter = ('dataset_slug', 'created_at')
    search_fields = ('=id', '=workspace__id', '=request_id', '=dataset_slug')
    date_hierarchy = 'created_at'
    sensitive_fields = ('response',)


@admin.register(MeterOutbox)
class MeterOutboxAdmin(BillingDiagnosticAdmin):
    fields = ('delivery', 'customer_id', 'event_name', 'status', 'attempts', 'first_attempt_at', 'next_attempt_at', 'lease_until', 'submitted_at', 'error_code')
    list_display = ('delivery', 'status', 'attempts', 'next_attempt_at', 'submitted_at', 'error_code')
    list_filter = ('status', 'event_name')
    search_fields = ('=delivery__id', '=delivery__workspace__id', '=customer_id', '=error_code')


@admin.register(MeterReconciliation)
class MeterReconciliationAdmin(BillingDiagnosticAdmin):
    fields = ('id', 'workspace', 'start_at', 'end_at', 'expected_credits', 'remote_credits', 'status', 'checked_at')
    list_display = ('workspace', 'status', 'expected_credits', 'remote_credits', 'start_at', 'end_at', 'checked_at')
    list_filter = ('status', 'checked_at')
    search_fields = ('=workspace__id',)
    date_hierarchy = 'checked_at'


@admin.register(StripeEvent)
class StripeEventAdmin(BillingDiagnosticAdmin):
    fields = ('event_id', 'event_type', 'status', 'received_at', 'processed_at', 'error_code')
    list_display = ('event_id', 'event_type', 'status', 'received_at', 'processed_at', 'error_code')
    list_filter = ('status', 'event_type', 'received_at')
    search_fields = ('=event_id', '=error_code')
    date_hierarchy = 'received_at'
    sensitive_fields = ('payload',)


@admin.register(BillingConsent)
class BillingConsentAdmin(BillingDiagnosticAdmin):
    fields = ('id', 'workspace', 'identity', 'overage_enabled', 'spend_cap_cents', 'overage_cents_per_10000', 'policy_version', 'created_at')
    list_display = ('workspace', 'overage_enabled', 'spend_cap_cents', 'policy_version', 'created_at')
    list_filter = ('overage_enabled', 'policy_version', 'created_at')
    search_fields = ('=workspace__id', '=identity__subject')
    date_hierarchy = 'created_at'
