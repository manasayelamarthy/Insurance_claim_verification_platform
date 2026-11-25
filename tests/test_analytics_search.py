"""Tests for new analytics, search/filter, and notifications modules."""
import tempfile
import unittest
from pathlib import Path
import sys
import os

# Allow imports from project root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class TestAnalytics(unittest.TestCase):
    def test_import(self):
        from app.insurance.analytics import get_dashboard_stats  # noqa
        self.assertTrue(callable(get_dashboard_stats))

    def test_stats_with_real_db(self):
        """Analytics must return the expected keys for a live database."""
        from app.insurance.analytics import get_dashboard_stats
        project_root = Path(__file__).resolve().parents[1]
        stats = get_dashboard_stats(project_root)
        required_keys = {
            "total_claims", "approved", "rejected", "pending",
            "total_members", "approval_rate", "by_status",
            "recent_activity", "top_hospitals", "monthly_volume",
        }
        self.assertTrue(required_keys.issubset(stats.keys()))
        self.assertIsInstance(stats["total_claims"], int)
        self.assertIsInstance(stats["approval_rate"], (int, float))
        self.assertIsInstance(stats["by_status"], list)
        self.assertIsInstance(stats["monthly_volume"], list)


class TestSearchFilter(unittest.TestCase):
    def test_import(self):
        from app.insurance.search_filter import search_claims, get_claim_timeline  # noqa
        self.assertTrue(callable(search_claims))
        self.assertTrue(callable(get_claim_timeline))

    def test_search_all(self):
        """search_claims with no filters must return paginated dict."""
        from app.insurance.search_filter import search_claims
        project_root = Path(__file__).resolve().parents[1]
        result = search_claims(project_root)
        self.assertIn("items", result)
        self.assertIn("total", result)
        self.assertIn("page", result)
        self.assertIn("pages", result)
        self.assertIsInstance(result["items"], list)

    def test_search_query(self):
        """Query filter must not raise and must return a subset."""
        from app.insurance.search_filter import search_claims
        project_root = Path(__file__).resolve().parents[1]
        all_result = search_claims(project_root)
        filtered = search_claims(project_root, query="CLM")
        self.assertLessEqual(filtered["total"], all_result["total"])

    def test_search_bad_sort_col(self):
        """Invalid sort column must fall back gracefully, not raise."""
        from app.insurance.search_filter import search_claims
        project_root = Path(__file__).resolve().parents[1]
        result = search_claims(project_root, sort_by="injected_col; DROP TABLE claims;")
        self.assertIn("items", result)

    def test_timeline_known_claim(self):
        """get_claim_timeline for seeded claim must return a list."""
        from app.insurance.search_filter import get_claim_timeline
        project_root = Path(__file__).resolve().parents[1]
        timeline = get_claim_timeline(project_root, "CLM-1001")
        self.assertIsInstance(timeline, list)

    def test_timeline_unknown_claim(self):
        """Unknown claim must return empty list, not raise."""
        from app.insurance.search_filter import get_claim_timeline
        project_root = Path(__file__).resolve().parents[1]
        result = get_claim_timeline(project_root, "CLM-DOES-NOT-EXIST-99999")
        self.assertEqual(result, [])


class TestNotifications(unittest.TestCase):
    def test_import(self):
        from app.insurance.notifications import notify_claim_status_changed  # noqa
        self.assertTrue(callable(notify_claim_status_changed))

    def test_no_email_does_nothing(self):
        """None email must not raise."""
        from app.insurance.notifications import notify_claim_status_changed
        notify_claim_status_changed(None, "CLM-TEST", "approved", "Test note")

    def test_stub_logs_without_smtp(self):
        """Without SMTP env vars the stub must log and not raise."""
        from app.insurance.notifications import notify_claim_status_changed
        for var in ("SMTP_HOST", "SMTP_USER", "SMTP_PASS"):
            os.environ.pop(var, None)
        notify_claim_status_changed("test@example.com", "CLM-001", "approved", "")
        notify_claim_status_changed("test@example.com", "CLM-002", "rejected", "Missing docs")
        notify_claim_status_changed("test@example.com", "CLM-003", "documents_requested", "")


class TestAnalyticsEndpoint(unittest.TestCase):
    """Integration test: analytics and search route handlers."""
    def test_analytics_endpoint_returns_stats(self):
        from app.web import analytics_overview
        data = analytics_overview()
        self.assertIn("total_claims", data)
        self.assertIn("approval_rate", data)

    def test_analytics_endpoint_rejects_member_role(self):
        from types import SimpleNamespace
        from fastapi import HTTPException
        from app.web import analytics_overview
        fake_request = SimpleNamespace(state=SimpleNamespace(auth={"role": "member", "user_id": "user_001"}))
        with self.assertRaises(HTTPException) as ctx:
            analytics_overview(request=fake_request)
        self.assertEqual(ctx.exception.status_code, 403)


class TestClaimSearchEndpoint(unittest.TestCase):
    def test_search_endpoint_returns_paginated_results(self):
        from app.web import search_claims_endpoint
        data = search_claims_endpoint()
        self.assertIn("items", data)
        self.assertIn("total", data)

    def test_search_endpoint_rejects_member_role(self):
        from types import SimpleNamespace
        from fastapi import HTTPException
        from app.web import search_claims_endpoint
        fake_request = SimpleNamespace(state=SimpleNamespace(auth={"role": "member", "user_id": "user_001"}))
        with self.assertRaises(HTTPException) as ctx:
            search_claims_endpoint(request=fake_request)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_landing_and_app_routes(self):
        from app.web import app_home, health_check, home
        self.assertEqual(health_check()["status"], "ok")
        self.assertTrue(str(home().path).endswith("index.html"))
        self.assertTrue(str(app_home().path).endswith("index.html"))


if __name__ == "__main__":
    unittest.main()
