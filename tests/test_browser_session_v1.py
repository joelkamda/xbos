"""Disposable local PostgreSQL tests for additive browser-session.v1 authority."""
import os
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://xbos_vn0_test@127.0.0.1:55439/xbos_vn0_test")
os.environ.setdefault("JWT_SECRET", "unit-test-only-not-for-deployment")
os.environ.setdefault("GATEWAY_API_KEY", "unused-test-placeholder")

import unittest
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from database import Base
from core.users.user_model import User
from core.tenants.tenant_model import Tenant, Branch
from core.auth.auth_service import AuthService
from core.auth.browser_session_model import BrowserSession
from core.auth.browser_session_service import (
    BrowserSessionDenied, BrowserConcurrentRefresh, browser_access,
    create_session, continue_session, decode_token, revoke_session,
    validate_browser_access,
)


class BrowserSessionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(os.environ["DATABASE_URL"])
        for model in (BrowserSession, User, Branch, Tenant):
            model.__table__.drop(self.engine, checkfirst=True)
        for model in (Tenant, Branch, User, BrowserSession):
            model.__table__.create(self.engine, checkfirst=True)
        self.db = Session(self.engine)
        self.db.add(Tenant(id=101, code="TEST", name="Test", country_code="CM",
                           currency="XAF", locale="fr", timezone="Africa/Douala"))
        self.db.add(Branch(id=201, tenant_id=101, branch_code="TEST-1",
                           name="Test Branch", is_active=True))
        self.db.add(User(id=301, username="tester", password_hash="unused",
                         tenant_id=101, branch_id=201, role="cashier", is_active=True))
        self.db.commit()
        self.permission_patch = patch.object(
            AuthService, "resolve_effective_permissions",
            lambda _self, _db, role_name: ["sale.view"] if role_name == "cashier" else ["sale.create"],
        )
        self.permission_patch.start()
        self.row, self.access, self.refresh = create_session(self.db, 301, 101, 201)

    def tearDown(self):
        self.permission_patch.stop()
        self.db.close()
        self.engine.dispose()

    def test_authorized_request_revalidates_session(self):
        identity = validate_browser_access(self.db, self.access)
        self.assertEqual(identity["tenant_id"], 101)
        self.assertEqual(identity["permissions"], ["sale.view"])
        self.assertEqual(decode_token(self.access, "browser_access")["sid"], self.row.session_id)

    def test_rotate_previous_grace_and_replay(self):
        _, new_access, new_refresh = continue_session(self.db, self.refresh)
        self.assertNotEqual(new_refresh, self.refresh)
        self.assertEqual(validate_browser_access(self.db, new_access)["role"], "cashier")
        with self.assertRaises(BrowserConcurrentRefresh):
            continue_session(self.db, self.refresh)
        # Force grace expiry, then replay must revoke the entire family.
        self.row.previous_refresh_valid_until = self.row.created_at
        self.db.commit()
        with self.assertRaises(BrowserSessionDenied):
            continue_session(self.db, self.refresh)
        with self.assertRaises(BrowserSessionDenied):
            validate_browser_access(self.db, new_access)

    def test_logout_is_idempotent_and_access_fails_immediately(self):
        revoke_session(self.db, self.refresh)
        revoke_session(self.db, self.refresh)
        with self.assertRaises(BrowserSessionDenied):
            validate_browser_access(self.db, self.access)

    def test_user_disable_and_role_change_not_stale(self):
        user = self.db.get(User, 301)
        user.role = "manager"
        self.db.commit()
        self.assertEqual(validate_browser_access(self.db, self.access)["permissions"], ["sale.create"])
        user.is_active = False
        self.db.commit()
        with self.assertRaises(BrowserSessionDenied):
            validate_browser_access(self.db, self.access)

    def test_cross_context_change_fails_closed(self):
        self.db.add(Branch(id=202, tenant_id=101, branch_code="TEST-2",
                           name="Other Branch", is_active=True))
        self.db.commit()
        user = self.db.get(User, 301)
        user.branch_id = 202
        self.db.commit()
        with self.assertRaises(BrowserSessionDenied):
            validate_browser_access(self.db, self.access)

    def test_older_generation_replay_revokes_family(self):
        _, access2, token2 = continue_session(self.db, self.refresh)
        _, access3, _token3 = continue_session(self.db, token2)
        with self.assertRaises(BrowserSessionDenied):
            continue_session(self.db, self.refresh)
        with self.assertRaises(BrowserSessionDenied):
            validate_browser_access(self.db, access3)

    def test_parallel_continuation_is_bounded_without_false_revocation(self):
        from concurrent.futures import ThreadPoolExecutor
        from sqlalchemy.orm import Session
        def worker():
            with Session(self.engine) as db:
                try:
                    continue_session(db, self.refresh)
                    return "ROTATED"
                except BrowserConcurrentRefresh:
                    return "BENIGN_CONCURRENT"
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _i: worker(), range(2)))
        self.assertCountEqual(results, ["ROTATED", "BENIGN_CONCURRENT"])
        self.db.expire_all()
        self.assertIsNone(self.db.get(BrowserSession, self.row.session_id).revoked_at)

    def test_invalid_session_or_wrong_token_type_fails(self):
        with self.assertRaises(BrowserSessionDenied):
            validate_browser_access(self.db, self.refresh)


if __name__ == "__main__":
    unittest.main()
