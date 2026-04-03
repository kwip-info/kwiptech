from django.apps import AppConfig


class BillingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "plane.billing"

    def ready(self):
        from django.db.models.signals import post_migrate
        post_migrate.connect(_sync_stripe_prices_handler, sender=self)


def _sync_stripe_prices_handler(sender, **kwargs):
    """Sync Stripe price IDs from env vars to the Pro plan record after migrations."""
    from django.conf import settings

    price_pro = getattr(settings, "STRIPE_PRICE_PRO", "")
    price_obj = getattr(settings, "STRIPE_PRICE_OBJECT_OVERAGE", "")
    price_prin = getattr(settings, "STRIPE_PRICE_PRINCIPAL_OVERAGE", "")

    if not price_pro:
        return

    try:
        from plane.billing.models import Plan

        Plan.objects.filter(id="pro").update(
            stripe_base_price_id=price_pro,
            stripe_object_price_id=price_obj,
            stripe_principal_price_id=price_prin,
        )
    except Exception:
        pass
