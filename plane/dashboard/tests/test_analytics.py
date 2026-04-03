"""Tests for analytics pages — key analytics, sync status, dashboard charts."""

from django.test import TestCase

from plane.core.models import Account, Application


class DashboardHomeTest(TestCase):

    def setUp(self):
        self.client.get("/dashboard/")

    def test_returns_200(self):
        response = self.client.get("/dashboard/")
        assert response.status_code == 200

    def test_has_summary_cards(self):
        response = self.client.get("/dashboard/")
        self.assertContains(response, "API Keys")
        self.assertContains(response, "Sync Status")
        self.assertContains(response, "Active Objects")
        self.assertContains(response, "Audit Activity")

    def test_has_activity_feed(self):
        response = self.client.get("/dashboard/")
        self.assertContains(response, "Recent Activity")

    def test_has_key_status_chart(self):
        response = self.client.get("/dashboard/")
        self.assertContains(response, "Key Status")

    def test_has_activity_chart(self):
        response = self.client.get("/dashboard/")
        self.assertContains(response, "SDK Activity")

    def test_has_resource_trends_chart(self):
        response = self.client.get("/dashboard/")
        self.assertContains(response, "Resource Trends")

    def test_has_audit_volume_chart(self):
        response = self.client.get("/dashboard/")
        self.assertContains(response, "Audit Volume")


class KeyAnalyticsPageTest(TestCase):

    def setUp(self):
        self.client.get("/dashboard/")
        self.account = Account.objects.get(id="test_account")
        self.app = Application.objects.get(id="test_app")

    def test_returns_200(self):
        response = self.client.get("/dashboard/keys/analytics/")
        assert response.status_code == 200

    def test_uses_correct_template(self):
        response = self.client.get("/dashboard/keys/analytics/")
        self.assertTemplateUsed(response, "dashboard/key_analytics.html")

    def test_has_lifecycle_stats(self):
        response = self.client.get("/dashboard/keys/analytics/")
        self.assertContains(response, "Total Keys")
        self.assertContains(response, "Active")
        self.assertContains(response, "Revoked")
        self.assertContains(response, "Avg Age")

    def test_has_recency_chart(self):
        response = self.client.get("/dashboard/keys/analytics/")
        self.assertContains(response, "Last Used Recency")

    def test_has_creation_chart(self):
        response = self.client.get("/dashboard/keys/analytics/")
        self.assertContains(response, "Key Creation")

    def test_has_back_link(self):
        response = self.client.get("/dashboard/keys/analytics/")
        self.assertContains(response, "Back to keys")

    def test_shows_correct_counts_with_keys(self):
        from plane.dashboard.services import create_api_key
        create_api_key(self.account, self.app, "test", "k1")
        create_api_key(self.account, self.app, "test", "k2")
        # Default env is "test", so both keys should appear
        response = self.client.get("/dashboard/keys/analytics/")
        self.assertContains(response, ">2<")  # total
        self.assertContains(response, ">2<")  # active


class SyncStatusPageTest(TestCase):

    def setUp(self):
        self.client.get("/dashboard/")

    def test_returns_200(self):
        response = self.client.get("/dashboard/sync/")
        assert response.status_code == 200

    def test_uses_correct_template(self):
        response = self.client.get("/dashboard/sync/")
        self.assertTemplateUsed(response, "dashboard/sync.html")

    def test_shows_disconnected_with_no_data(self):
        response = self.client.get("/dashboard/sync/")
        self.assertContains(response, "Disconnected")

    def test_has_setup_link(self):
        response = self.client.get("/dashboard/sync/")
        self.assertContains(response, "Setup guide")


class KeyAnalyticsFilterTest(TestCase):

    def setUp(self):
        self.client.get("/dashboard/")
        self.account = Account.objects.get(id="test_account")
        self.app = Application.objects.get(id="test_app")

    def test_default_uses_active_app(self):
        response = self.client.get("/dashboard/keys/analytics/")
        assert response.status_code == 200
        # Uses global app toggle (default app)
        self.assertContains(response, "Test App")

    def test_key_filter(self):
        from plane.dashboard.services import create_api_key
        key, _ = create_api_key(self.account, self.app, "test", "filtered")
        response = self.client.get(f"/dashboard/keys/analytics/?keys={key.id}")
        assert response.status_code == 200
        self.assertContains(response, "1 keys selected")


class KeyDetailUsageSectionTest(TestCase):

    def setUp(self):
        self.client.get("/dashboard/")
        self.account = Account.objects.get(id="test_account")
        self.app = Application.objects.get(id="test_app")

    def test_detail_has_usage_section(self):
        from plane.dashboard.services import create_api_key
        key, _ = create_api_key(self.account, self.app, "test", "usage")
        response = self.client.get(f"/dashboard/keys/{key.id}/")
        self.assertContains(response, "Usage")
        self.assertContains(response, "View in analytics")

    def test_detail_links_to_filtered_analytics(self):
        from plane.dashboard.services import create_api_key
        key, _ = create_api_key(self.account, self.app, "test", "link")
        response = self.client.get(f"/dashboard/keys/{key.id}/")
        self.assertContains(response, f"?keys={key.id}")


class KeysPageAnalyticsLinkTest(TestCase):

    def setUp(self):
        self.client.get("/dashboard/keys/")

    def test_keys_page_has_analytics_link(self):
        response = self.client.get("/dashboard/keys/")
        self.assertContains(response, "Analytics")
        self.assertContains(response, "/dashboard/keys/analytics/")
