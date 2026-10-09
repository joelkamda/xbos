"""Isolated HTTPS TestClient proof for the additive browser-session profile."""
import os
os.environ["DATABASE_URL"] = "postgresql+psycopg2://xbos_vn0_test@127.0.0.1:55439/xbos_vn0_test"
os.environ["JWT_SECRET"] = "unit-test-only-not-for-deployment"
os.environ["GATEWAY_API_KEY"] = "unused-test-placeholder"
os.environ["XBOS_BROWSER_ALLOWED_ORIGINS"] = "https://testserver"

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from database import Base
from core.tenants.tenant_model import Tenant, Branch
from core.users.user_model import User
from core.auth.browser_session_model import BrowserSession
from core.auth.auth_service import AuthService
from core.auth.password_service import PasswordService
from core.security.jwt_service import JWTService
from main import app

HEADERS = {"Origin": "https://testserver", "X-XBOS-Browser-Session": "1"}

class BrowserSessionHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(os.environ["DATABASE_URL"])
        for model in (BrowserSession, User, Branch, Tenant):
            model.__table__.drop(cls.engine, checkfirst=True)
        for model in (Tenant, Branch, User, BrowserSession):
            model.__table__.create(cls.engine, checkfirst=True)
        with Session(cls.engine) as db:
            db.add(Tenant(id=101, code="TEST", name="Test", country_code="CM",
                          currency="XAF", locale="fr", timezone="Africa/Douala"))
            db.add(Branch(id=201, tenant_id=101, branch_code="TEST-1",
                          name="Test Branch", is_active=True))
            db.add(User(id=301, username="tester", password_hash=PasswordService().hash("unit-pass"),
                        tenant_id=101, branch_id=201, role="cashier", is_active=True))
            db.commit()

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        self.permissions = patch.object(
            AuthService, "resolve_effective_permissions",
            lambda _self, db, role_name: ["sale.view"],
        )
        self.permissions.start()
        self.client = TestClient(app, base_url="https://testserver")
        self.addCleanup(self.client.close)
        self.addCleanup(self.permissions.stop)

    def sign_in(self):
        return self.client.post(
            "/kernel/browser-session/v1/login",
            headers={**HEADERS, "X-Tenant-Code": "TEST", "X-Branch-Code": "TEST-1"},
            json={"username": "tester", "password": "unit-pass"},
        )

    def test_legacy_bearer_and_refresh_header_preserved(self):
        jwt = JWTService()
        token = jwt.create_access_token(301, tenant_id=101, branch_id=201,
                                        role="cashier", permissions=["sale.view"])
        result = self.client.get("/kernel/whoami", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(result.status_code, 200, result.text)
        refresh = jwt.create_refresh_token(301)
        result = self.client.post("/kernel/auth/refresh", headers={"X-Refresh-Token": refresh})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertIn("access_token", result.json())

    def test_invalid_credentials_do_not_create_session(self):
        result = self.client.post("/kernel/browser-session/v1/login",
                                  headers={**HEADERS, "X-Tenant-Code": "TEST", "X-Branch-Code": "TEST-1"},
                                  json={"username": "tester", "password": "wrong"})
        self.assertNotEqual(result.status_code, 200)
        self.assertNotIn("__Host-xbos_refresh", result.headers.get("set-cookie", ""))

    def test_origin_and_non_simple_header_mandatory(self):
        bad = self.client.post("/kernel/browser-session/v1/login",
                               headers={"X-Tenant-Code": "TEST", "X-Branch-Code": "TEST-1"},
                               json={"username": "tester", "password": "dummy"})
        self.assertEqual(bad.status_code, 403)
        bad = self.client.post("/kernel/browser-session/v1/login",
                               headers={"Origin": "https://testserver", "X-Tenant-Code": "TEST", "X-Branch-Code": "TEST-1"},
                               json={"username": "tester", "password": "dummy"})
        self.assertEqual(bad.status_code, 403)

    def test_cookie_login_continue_logout_and_stale_access(self):
        login = self.sign_in()
        self.assertEqual(login.status_code, 200, login.text)
        self.assertNotIn("refresh_token", login.json())
        self.assertEqual(login.json()["expires_in"], 900)
        cookie = login.headers.get("set-cookie", "")
        for flag in ("__Host-xbos_refresh=", "httponly", "secure", "samesite=lax", "path=/"):
            self.assertIn(flag.lower(), cookie.lower())
        access = login.json()["access_token"]
        who = self.client.get("/kernel/whoami", headers={"Authorization": f"Bearer {access}"})
        self.assertEqual(who.status_code, 200, who.text)
        self.assertEqual(who.json()["permissions"], ["sale.view"])
        refreshed = self.client.post("/kernel/browser-session/v1/continue", headers=HEADERS)
        self.assertEqual(refreshed.status_code, 200, refreshed.text)
        self.assertNotIn("refresh_token", refreshed.json())
        logged_out = self.client.post("/kernel/browser-session/v1/logout", headers=HEADERS)
        self.assertEqual(logged_out.status_code, 200, logged_out.text)
        self.assertEqual(self.client.post("/kernel/browser-session/v1/logout", headers=HEADERS).status_code, 200)
        stale = self.client.get("/kernel/whoami", headers={"Authorization": f"Bearer {access}"})
        self.assertEqual(stale.status_code, 401, stale.text)

if __name__ == "__main__":
    unittest.main()
