"""Provision a test account, org, and API key for SDK integration testing.

Creates the minimum resources needed to run the pyscoped SDK against
this platform instance. Outputs a JSON config that can be fed directly
to the SDK smoke test.

Usage:
    python manage.py create_test_sdk_config
    python manage.py create_test_sdk_config --base-url http://web:8000/v1
    python manage.py create_test_sdk_config --json > /tmp/sdk-test-config.json

Idempotent: reuses existing test account/org if present.
"""

import json
from uuid import uuid4

from django.core.management.base import BaseCommand
from django.utils import timezone

from plane.billing.models import Plan
from plane.core.models import Account, ApiKey, Application, Organization


TEST_ACCOUNT_ID = "sdk-integration-test"
TEST_ORG_SLUG = "sdk-test-org"


class Command(BaseCommand):
    help = "Provision a test account + API key for SDK integration testing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--base-url",
            default="http://localhost:8000/v1",
            help="Platform API base URL (default: http://localhost:8000/v1)",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Output only JSON (no human-readable messages)",
        )

    def handle(self, *args, **options):
        base_url = options["base_url"].rstrip("/")
        json_only = options["json"]

        # Ensure plans exist
        if not Plan.objects.filter(id="free").exists():
            from django.core.management import call_command
            call_command("seed_plans", verbosity=0)

        # Account (idempotent)
        account, created = Account.objects.get_or_create(
            id=TEST_ACCOUNT_ID,
            defaults={"email": "sdk-test@localhost"},
        )
        if not json_only and created:
            self.stdout.write(f"  Created account: {account.id}")

        # Organization (idempotent)
        org, created = Organization.objects.get_or_create(
            slug=TEST_ORG_SLUG,
            defaults={
                "id": uuid4().hex,
                "name": "SDK Test Org",
                "owner": account,
                "is_personal": True,
                "plan": "free",
            },
        )
        if not json_only and created:
            self.stdout.write(f"  Created org: {org.name} ({org.id})")

        # Application (idempotent)
        app, created = Application.objects.get_or_create(
            organization=org,
            slug="default",
            defaults={
                "id": uuid4().hex,
                "name": "Default",
                "is_default": True,
            },
        )

        # API key — always create a fresh one
        full_key, key_hash = ApiKey.generate_key("test")
        key = ApiKey.objects.create(
            id=uuid4().hex,
            account=account,
            application=app,
            key_hash=key_hash,
            key_prefix=full_key[:13],
            environment="test",
            label="SDK integration test",
        )

        config = {
            "base_url": base_url,
            "api_key": full_key,
            "account_id": account.id,
            "org_id": org.id,
            "app_id": app.id,
            "key_id": key.id,
        }

        if json_only:
            self.stdout.write(json.dumps(config))
        else:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("SDK test config:"))
            self.stdout.write(json.dumps(config, indent=2))
            self.stdout.write("")
            self.stdout.write("Run the smoke test:")
            self.stdout.write(
                f"  python -m scoped.testing.integration "
                f"--base-url {base_url} --api-key {full_key}"
            )
