"""Tests for ClerkAuthMiddleware."""

from unittest.mock import patch

from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from plane.auth.jwt import JwtVerificationError
from plane.auth.middleware import ClerkAuthMiddleware
from plane.core.models import Account


def _ok_response(request):
    return HttpResponse("OK")


class TestClerkAuthMiddleware(TestCase):

    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = ClerkAuthMiddleware(_ok_response)

    def test_skipped_paths_pass_through(self):
        for path in ["/admin/login/", "/v1/ping", "/static/css/app.css"]:
            request = self.factory.get(path)
            request.clerk_user = None
            request.clerk_user_id = None
            response = self.middleware(request)
            assert response.status_code == 200, f"Expected 200 for {path}"

    def test_public_paths_pass_without_auth(self):
        for path in ["/", "/pricing", "/sign-in", "/security"]:
            request = self.factory.get(path)
            response = self.middleware(request)
            assert response.status_code == 200, f"Expected 200 for {path}"

    def test_protected_path_redirects_without_auth(self):
        request = self.factory.get("/dashboard/")
        response = self.middleware(request)
        assert response.status_code == 302
        assert response.url == "/sign-in"

    @patch("plane.auth.middleware.verify_clerk_token")
    def test_protected_invalid_token_redirects(self, mock_verify):
        mock_verify.side_effect = JwtVerificationError("bad token")
        request = self.factory.get("/dashboard/")
        request.COOKIES["__session"] = "garbage-token"
        response = self.middleware(request)
        assert response.status_code == 302
        assert response.url == "/sign-in"

    @patch("plane.auth.middleware.get_or_create_account")
    @patch("plane.auth.middleware.verify_clerk_token")
    def test_protected_valid_token_sets_clerk_user(self, mock_verify, mock_get_account):
        account = Account(id="acc_1", email="user@test.com", clerk_user_id="user_abc")
        mock_verify.return_value = {"sub": "user_abc", "email": "user@test.com"}
        mock_get_account.return_value = account

        request = self.factory.get("/dashboard/")
        request.COOKIES["__session"] = "valid-token"
        response = self.middleware(request)

        assert response.status_code == 200
        assert request.clerk_user == account
        assert request.clerk_user_id == "user_abc"

    @patch("plane.auth.middleware.get_or_create_account")
    @patch("plane.auth.middleware.verify_clerk_token")
    def test_public_path_still_sets_clerk_user_if_token_present(self, mock_verify, mock_get_account):
        account = Account(id="acc_2", email="nav@test.com", clerk_user_id="user_nav")
        mock_verify.return_value = {"sub": "user_nav", "email": "nav@test.com"}
        mock_get_account.return_value = account

        request = self.factory.get("/")
        request.COOKIES["__session"] = "valid-token"
        response = self.middleware(request)

        assert response.status_code == 200
        assert request.clerk_user == account

    def test_public_path_invalid_token_does_not_redirect(self):
        with patch("plane.auth.middleware.verify_clerk_token") as mock_verify:
            mock_verify.side_effect = JwtVerificationError("expired")
            request = self.factory.get("/")
            request.COOKIES["__session"] = "expired-token"
            response = self.middleware(request)
            assert response.status_code == 200

    def test_psc_bearer_not_intercepted(self):
        request = self.factory.get("/dashboard/", HTTP_AUTHORIZATION="Bearer psc_live_abc123")
        response = self.middleware(request)
        assert response.status_code == 302

    @patch("plane.auth.middleware.get_or_create_account")
    @patch("plane.auth.middleware.verify_clerk_token")
    def test_clerk_instance_cookie_accepted(self, mock_verify, mock_get_account):
        account = Account(id="acc_3", email="inst@test.com", clerk_user_id="user_inst")
        mock_verify.return_value = {"sub": "user_inst"}
        mock_get_account.return_value = account

        request = self.factory.get("/dashboard/")
        request.COOKIES["__session_qRPV0b5X"] = "valid-token"
        response = self.middleware(request)

        assert response.status_code == 200
        assert request.clerk_user_id == "user_inst"
