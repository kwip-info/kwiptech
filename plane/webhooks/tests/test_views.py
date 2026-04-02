"""Tests for the webhook endpoint."""

import json
from unittest.mock import patch

from django.test import TestCase

from plane.core.defaults import seed_permissions
from plane.core.models import Account, Organization, Permission


class ClerkWebhookEndpointTest(TestCase):

    def test_get_not_allowed(self):
        response = self.client.get("/webhooks/clerk/")
        assert response.status_code == 405

    @patch("plane.webhooks.verification.verify_webhook", side_effect=Exception("bad sig"))
    def test_bad_signature_returns_400(self, mock_verify):
        response = self.client.post(
            "/webhooks/clerk/",
            data=json.dumps({"type": "test"}),
            content_type="application/json",
        )
        assert response.status_code == 400

    @patch("plane.webhooks.verification.verify_webhook")
    def test_unhandled_event_returns_ignored(self, mock_verify):
        mock_verify.return_value = {"type": "user.created", "data": {}}
        response = self.client.post(
            "/webhooks/clerk/",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ignored"

    @patch("plane.webhooks.verification.verify_webhook")
    def test_organization_created_end_to_end(self, mock_verify):
        seed_permissions(Permission)
        Account.objects.create(id="acc_e2e", clerk_user_id="user_e2e")
        mock_verify.return_value = {
            "type": "organization.created",
            "data": {
                "id": "org_e2e",
                "name": "E2E Corp",
                "slug": "e2e-corp",
                "created_by": "user_e2e",
            },
        }
        response = self.client.post(
            "/webhooks/clerk/",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        assert Organization.objects.filter(clerk_org_id="org_e2e").exists()

    @patch("plane.webhooks.verification.verify_webhook")
    def test_handler_error_returns_500(self, mock_verify):
        mock_verify.return_value = {
            "type": "organization.created",
            "data": {},  # Missing required fields will cause KeyError
        }
        with self.assertLogs("pyscoped.plane.webhooks.views", level="ERROR"):
            response = self.client.post(
                "/webhooks/clerk/",
                data=json.dumps({}),
                content_type="application/json",
            )
        assert response.status_code == 500
