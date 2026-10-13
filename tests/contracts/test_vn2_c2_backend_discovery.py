"""C2 read-only discovery contract and security tests; no real PostgreSQL connection."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch
import os

from fastapi import FastAPI
from fastapi.testclient import TestClient

# Isolated local test-only engine configuration; never connects to this URL.
with patch.dict(os.environ, {"DATABASE_URL": "postgresql+psycopg2://readonly:unused@127.0.0.1:65432/xafpay_c2_never_connect", "JWT_SECRET": "local-c2-test-only-nonsecret-do-not-use-in-runtime"}):
    from database import get_db
    from core.auth import pack_template_discovery_router as http
    from core.auth.browser_session_service import BrowserSessionDenied
    from core.middleware.auth_middleware import AuthMiddleware
    from pack_platform.discovery_read_model import read_discovery

ROOT = Path(__file__).resolve().parents[2]
C1 = json.loads((ROOT/"contracts/platform/v1/vn2_pack_template_discovery_v1.json").read_text(encoding="utf-8"))


class Records:
    def __init__(self, values):
        self.values = values

    def mappings(self):
        return self

    def all(self):
        return self.values


class MemoryDB:
    def __init__(self, *, tenant=17, fail=False):
        self.tenant = tenant
        self.fail = fail
        self.queries = []
        self.rollback_calls = 0

    def execute(self, statement, params=None):
        sql = str(statement)
        self.queries.append((sql, params))
        if self.fail:
            raise RuntimeError("SENSITIVE_DATABASE_ERROR")
        if sql == "SET TRANSACTION READ ONLY":
            return Records([])
        if "FROM public.pk_packs AS p" in sql:
            return Records([
                {"pack_id": 7, "pack_code": "alpha", "owner_code": "pk",
                 "pack_kind": "capability", "pack_version": "1.0",
                 "manifest_sha256": "a"*64, "retention_required": True},
                {"pack_id": 9, "pack_code": "zeta", "owner_code": "pk",
                 "pack_kind": "payment_connector", "pack_version": "2.0",
                 "manifest_sha256": "b"*64, "retention_required": False},
            ])
        if "FROM public.pk_tenant_pack_installations AS i" in sql:
            return Records(
                [{"pack_id":7,"lifecycle_status":"active","pack_version":"1.0","row_version":2}]
                if params == {"tenant_id": 17} else [])
        if "FROM public.pk_templates AS t" in sql:
            return Records([
                {"template_id":5,"template_code":"tpl.neutral","owner_code":"pk",
                 "template_version_id":15,"template_version":"1",
                 "template_sha256":"c"*64, "industry_semantic_ref":"semantic:neutral",
                 "operating_model_semantic_ref":"model:neutral"}
            ])
        if "FROM public.pk_template_pack_requirements AS r" in sql:
            return Records([
                {"template_version_id":15,"pack_code":"zeta","pack_version":"2.0","requirement_kind":"optional"},
                {"template_version_id":15,"pack_code":"alpha","pack_version":"1.0","requirement_kind":"required"}
            ])
        if "FROM public.pk_tenant_template_bindings AS b" in sql:
            return Records(
                [{"template_id":5,"template_version":"1","row_version":3,
                  "selected_optional_packs":["zeta","alpha"]}]
                if params == {"tenant_id":17} else [])
        raise AssertionError("UNAUTHORIZED_TABLE_OR_QUERY")

    def rollback(self):
        self.rollback_calls += 1

    def close(self):
        return None


def identity(tenant=17):
    return {"user_id": 11, "tenant_id": tenant, "branch_id": 21,
            "role": "platform_user", "permissions": []}


def me(tenant=17):
    return {"id": 11, "tenant_id": tenant, "branch_id": 21,
            "role": "platform_user", "permissions": []}


class PlatformDiscoveryContract(unittest.TestCase):
    def make_client(self, db, authority=None, user=None):
        app = FastAPI()
        app.include_router(http.router, prefix="/kernel")
        app.add_middleware(AuthMiddleware)
        app.dependency_overrides[get_db] = lambda: db
        self.auth_patcher = patch.object(http, "validate_browser_access", side_effect=lambda _db, _token: authority or identity())
        self.me_patcher = patch.object(http, "AuthService")
        service = self.me_patcher.start().return_value
        service.me.side_effect = lambda **kwargs: user or me()
        self.auth_patcher.start()
        self.addCleanup(self.auth_patcher.stop)
        self.addCleanup(self.me_patcher.stop)
        return TestClient(app)

    def test_schema_and_safe_projection(self):
        from tests.contracts.test_vn2_c1_discovery_contract import validate_subset_schema
        db=MemoryDB()
        result=read_discovery(db,17)
        validate_subset_schema(C1["response_schema"],result)
        self.assertEqual(set(result),{"schema","tenant_ref","packs","templates"})
        self.assertEqual(result["packs"][0]["tenant_state"]["status"],"ACTIVE")
        self.assertEqual(result["templates"][0]["tenant_state"]["status"],"APPLIED")
        self.assertEqual(result["templates"][0]["tenant_state"]["selected_optional_packs"],["alpha","zeta"])
        self.assertEqual([x["pack_code"] for x in result["templates"][0]["versions"][0]["requirements"]],["alpha","zeta"])
        self.assertNotIn("manifest_json",json.dumps(result))
        self.assertNotIn("template_json",json.dumps(result))

    def test_tenant_scope_and_explicit_absence(self):
        db=MemoryDB()
        result=read_discovery(db,18)
        self.assertEqual(result["tenant_ref"],18)
        self.assertEqual(result["packs"][0]["tenant_state"],{"status":"ABSENT"})
        self.assertEqual(result["templates"][0]["tenant_state"],{"status":"ABSENT"})
        scoped=[params for sql,params in db.queries if ":tenant_id" in sql]
        self.assertEqual(scoped,[{"tenant_id":18},{"tenant_id":18}])

    def test_empty_catalog_without_defaults(self):
        db=MemoryDB()
        db.execute = lambda statement,params=None: Records([])
        self.assertEqual(read_discovery(db,17),{
            "schema":"xbos.platform.pack-template-discovery.v1","tenant_ref":17,"packs":[],"templates":[]
        })

    def test_invalid_untrusted_tenant_rejected(self):
        for tenant in (0,-1,"17",True,None):
            with self.assertRaises(ValueError):
                read_discovery(MemoryDB(),tenant)

    def test_valid_server_browser_session(self):
        db=MemoryDB()
        client=self.make_client(db)
        with patch.object(http,"read_discovery",side_effect=lambda _db,tenant: read_discovery(_db,tenant)):
            response=client.get("/kernel/platform/v1/pack-template-discovery",headers={"Authorization":"Bearer valid"})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()["tenant_ref"],17)
        self.assertEqual(db.queries[0][0],"SET TRANSACTION READ ONLY")
        self.assertEqual(response.headers["cache-control"],"private, no-store")

    def test_missing_bearer_no_legacy_access(self):
        db=MemoryDB()
        client=self.make_client(db)
        for auth in (None,"Bearer ","Basic abc"):
            headers={} if auth is None else {"Authorization":auth}
            response=client.get("/kernel/platform/v1/pack-template-discovery",headers=headers)
            self.assertEqual(response.status_code,401,response.text)
            self.assertEqual(response.json(),{"error":{"code":"UNAUTHENTICATED"}})
        self.assertEqual(db.queries,[])

    def test_legacy_profile_rejected_by_browser_validator(self):
        client=self.make_client(MemoryDB())
        with patch.object(http,"validate_browser_access",side_effect=BrowserSessionDenied("TOKEN_TYPE_INVALID")):
            response=client.get("/kernel/platform/v1/pack-template-discovery",headers={"Authorization":"Bearer legacy"})
        self.assertEqual(response.status_code,401)
        self.assertEqual(response.json(),{"error":{"code":"UNAUTHENTICATED"}})

    def test_header_and_middleware_tenant_cannot_override(self):
        client=self.make_client(MemoryDB())
        with patch.object(http,"read_discovery",side_effect=lambda db,tenant: read_discovery(db,tenant)):
            response=client.get("/kernel/platform/v1/pack-template-discovery",headers={
                "Authorization":"Bearer browser","X-Tenant-Code":"spoof",
                "X-Branch-Code":"other"})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()["tenant_ref"],17)

    def test_cross_tenant_and_branch_denied(self):
        for user in (me(99),{**me(),"branch_id":44}):
            client=self.make_client(MemoryDB(),user=user)
            response=client.get("/kernel/platform/v1/pack-template-discovery",headers={"Authorization":"Bearer browser"})
            self.assertEqual(response.status_code,403,response.text)
            self.assertEqual(response.json(),{"error":{"code":"TENANT_CONTEXT_UNAVAILABLE"}})

    def test_missing_branch_denied(self):
        client=self.make_client(MemoryDB(),authority={**identity(),"branch_id":None})
        response=client.get("/kernel/platform/v1/pack-template-discovery",headers={"Authorization":"Bearer browser"})
        self.assertEqual(response.status_code,403)
        self.assertEqual(response.json(),{"error":{"code":"TENANT_CONTEXT_UNAVAILABLE"}})

    def test_query_override_denied(self):
        client=self.make_client(MemoryDB())
        response=client.get("/kernel/platform/v1/pack-template-discovery?tenant_id=21",headers={"Authorization":"Bearer browser"})
        self.assertEqual(response.status_code,403)
        self.assertEqual(response.json(),{"error":{"code":"TRUST_CONTEXT_UNAVAILABLE"}})

    def test_db_failure_safe_503(self):
        client=self.make_client(MemoryDB(fail=True))
        response=client.get("/kernel/platform/v1/pack-template-discovery",headers={"Authorization":"Bearer browser"})
        self.assertEqual(response.status_code,503)
        self.assertEqual(response.json(),{"error":{"code":"DISCOVERY_UNAVAILABLE"}})
        self.assertNotIn("SENSITIVE_DATABASE_ERROR",response.text)

    def test_source_read_only_and_exact_public_interface(self):
        source=(ROOT/"pack_platform/discovery_read_model.py").read_text(encoding="utf-8")
        for sql in ("FOR UPDATE","INSERT INTO","DELETE FROM","UPDATE "):
            self.assertNotIn(sql,source.upper())
        self.assertEqual(source.count("WHERE i.tenant_id = :tenant_id"),1)
        self.assertEqual(source.count("WHERE b.tenant_id = :tenant_id"),1)
        self.assertIn('ORDER BY p.pack_code COLLATE "C"',source)
        self.assertIn('ORDER BY t.template_code COLLATE "C"',source)


if __name__ == "__main__":
    unittest.main()
