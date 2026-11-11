"""N D1 source-only HTTP composition; real PC1/PC4/PC5/PA/PK classes.

Only repositories, tokens and identity binding are synthetic test fixtures.
NO hosted, database, runtime PC5-browser binding or merchant admission.
"""
from dataclasses import replace
from datetime import timedelta
from uuid import UUID

import jwt
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from platform_admin.neutral_d1_read_router import (
    router, BoundPC5Principal, NeutralReadServices,
    get_verified_pc5_binding, get_neutral_read_services,
    STRUCTURE_PERMISSION, PA_PERMISSION, PK_PERMISSION,
)
from core.platform.security_authority import (
    PermissionDefinition, RoleAssignment, ScopeType, StructuralScope,
)
from core.platform.structure.service import StructuralAuthority
from core.platform.operating_context import CapabilityContext, OperatingContextAuthority
from pack_platform.service import PackAuthority
from tests.contracts.test_pc5_identity_policy_audit import configured, NOW, SESSION
from tests.contracts.test_pc1_structural_authority import MemoryRepository
from tests.contracts.test_pa0123_platform_administration import authority as pa_authority

KEY = "only-a-disposable-N-http-test-key-NEVER-a-runtime-key"


class RuntimePC4Fixture:
    def __init__(self):
        self.allowed = True
        self.effective_to = NOW + timedelta(minutes=10)

    def capability_context(self, tenant_id, module_code, capability_code, as_of):
        return CapabilityContext(
            module_available=True, module_enabled=True,
            entitled=(self.allowed and tenant_id == 7 and as_of < self.effective_to),
            feature_active=True, permission_authorized=None,
        )


class InMemoryPKReadRepo:
    def __init__(self):
        self.states = {}

    def state(self, tenant_id, pack_code):
        return self.states.get((tenant_id, pack_code))


@pytest.fixture
def synthetic():
    pc5, pc5repo, identity = configured()
    for index, (permission, module, resource) in enumerate((
        (STRUCTURE_PERMISSION, "pc1", "structural_context"),
        (PA_PERMISSION, "pa", "commercial_entitlements"),
        (PK_PERMISSION, "pk", "pack_state"),
    )):
        pc5.register_permission(
            command_key=f"n-d1-register-{index}",
            definition=PermissionDefinition(
                permission, module, resource, "read",
                allowed_scopes=(ScopeType.TENANT,),
            ),
        )
    pc5.create_role(
        command_key="n-d1-role", role_code="n-neutral-reader", tenant_id=7,
        permissions=(STRUCTURE_PERMISSION, PA_PERMISSION, PK_PERMISSION),
    )
    pc5.assign_role(
        command_key="n-d1-role-assign",
        assignment=RoleAssignment(
            identity.id, 7, "n-neutral-reader",
            StructuralScope(ScopeType.TENANT, 7), NOW - timedelta(hours=1),
        ),
    )
    structural_repo = MemoryRepository()
    structural_repo.tenants[7] = replace(structural_repo.tenants.pop(1), id=7)
    for table in (
        structural_repo.organizations, structural_repo.legals,
        structural_repo.places,
    ):
        for (tenant_id, objid), row in list(table.items()):
            if tenant_id == 1:
                del table[(tenant_id, objid)]
                table[(7, objid)] = replace(row, tenant_id=7)
    structural_repo.mappings = {(7, 7): (11, 200)}
    pc4repo = RuntimePC4Fixture()
    pkrepo = InMemoryPKReadRepo()
    services = NeutralReadServices(
        pc5=pc5,
        pc4=OperatingContextAuthority(pc4repo),
        pc1=StructuralAuthority(structural_repo),
        pa=pa_authority(),
        pk=PackAuthority(pkrepo),
        clock=lambda: NOW,
    )
    app = FastAPI()
    app.include_router(router)
    seen = {"signed_claims": 0}

    def verified_test_binding(request: Request):
        header = request.headers.get("authorization") or ""
        if not header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="MISSING_BEARER")
        try:
            payload = jwt.decode(header[7:], KEY, algorithms=["HS256"])
            sid = UUID(str(payload["sid"]))
            assert payload["tenant_id"] == 7
            assert payload["branch_id"] == 7
        except (jwt.PyJWTError, KeyError, ValueError, AssertionError):
            raise HTTPException(status_code=401, detail="INVALID_SYNTHETIC_TOKEN")
        seen["signed_claims"] += 1
        return BoundPC5Principal(session_id=sid, tenant_id=7, branch_id=7)

    app.dependency_overrides[get_verified_pc5_binding] = verified_test_binding
    app.dependency_overrides[get_neutral_read_services] = lambda: services

    def signed(**changes):
        body = dict(sid=str(SESSION), tenant_id=7, branch_id=7, role="viewer")
        body.update(changes)
        return {"Authorization": "Bearer " + jwt.encode(body, KEY, algorithm="HS256")}

    return TestClient(app), services, pc5repo, pc4repo, pkrepo, seen, signed


def test_real_pc5_pc4_pc1_structural_authority_positive(synthetic):
    client, _services, _pc5repo, _pc4repo, _pkrepo, seen, signed = synthetic
    result = client.get("/kernel/neutral/v1/tenants/7/branches/7/context", headers=signed())
    assert result.status_code == 200, result.text
    assert result.json()["organization_unit_id"] == 11
    assert result.json()["location_id"] == 200
    assert result.json()["classification"] == "SOURCE_ONLY_NONOPERATIVE"
    assert seen["signed_claims"] == 1


def test_real_pa_projection_is_not_pc4_effective_authority(synthetic):
    client, *_rest, signed = synthetic
    result = client.get("/kernel/neutral/v1/tenants/7/commercial-entitlements", headers=signed())
    assert result.status_code == 200, result.text
    assert result.json()["projected_codes"] == []
    assert result.json()["operational"] is False


def test_real_pack_authority_absent_pack_is_not_auto_activated(synthetic):
    client, *_rest, signed = synthetic
    result = client.get("/kernel/neutral/v1/tenants/7/packs/neutral.foundation/state", headers=signed())
    assert result.status_code == 200, result.text
    assert result.json()["state"] == "not_installed"
    assert result.json()["operational"] is False


@pytest.mark.parametrize("path", [
    "/kernel/neutral/v1/tenants/7/branches/7/context",
    "/kernel/neutral/v1/tenants/7/commercial-entitlements",
    "/kernel/neutral/v1/tenants/7/packs/neutral.foundation/state",
])
def test_missing_bearer_401(path, synthetic):
    client = synthetic[0]
    assert client.get(path).status_code == 401


def test_bogus_signed_token_denies_401(synthetic):
    client, *_rest, signed = synthetic
    invalid = signed()
    invalid["Authorization"] = "Bearer " + jwt.encode(
        {"sid": str(SESSION), "tenant_id": 7, "branch_id": 7},
        "wrong-synthetic-key", algorithm="HS256",
    )
    assert client.get("/kernel/neutral/v1/tenants/7/branches/7/context", headers=invalid).status_code == 401


def test_client_role_claim_cannot_create_pc5_permission(synthetic):
    client, services, repo, *_rest, signed = synthetic
    repo.role_assignments.clear()
    result = client.get("/kernel/neutral/v1/tenants/7/branches/7/context",
                        headers=signed(role="superadmin"))
    assert result.status_code == 403


def test_wrong_tenant_and_branch_fail_closed(synthetic):
    client, *_rest, signed = synthetic
    for path in (
        "/kernel/neutral/v1/tenants/8/branches/7/context",
        "/kernel/neutral/v1/tenants/7/branches/99/context",
        "/kernel/neutral/v1/tenants/8/commercial-entitlements",
        "/kernel/neutral/v1/tenants/8/packs/neutral.foundation/state",
    ):
        assert client.get(path, headers=signed()).status_code == 403


def test_headers_cannot_override_server_verified_tenant(synthetic):
    client, *_rest, signed = synthetic
    headers = signed()
    headers.update({"X-Tenant-Code": "another", "X-Branch-Code": "99",
                    "X-PC5-Session": "attacker-session",
                    "X-Platform-Role": "superadmin"})
    response = client.get("/kernel/neutral/v1/tenants/7/branches/7/context",
                          headers=headers)
    assert response.status_code == 200
    assert response.json()["tenant_id"] == 7


def test_revoked_pc5_session_denies_403(synthetic):
    client, services, *_rest, signed = synthetic
    services.pc5.revoke_session(SESSION, NOW)
    assert client.get("/kernel/neutral/v1/tenants/7/branches/7/context",
                      headers=signed()).status_code == 403


def test_expired_pc5_session_denies_403(synthetic):
    client, services, repo, *_rest, signed = synthetic
    repo.sessions[SESSION] = replace(repo.sessions[SESSION], expires_at=NOW)
    assert client.get("/kernel/neutral/v1/tenants/7/branches/7/context",
                      headers=signed()).status_code == 403


def test_expired_pc4_entitlement_denies_403(synthetic):
    client, services, repo, pc4repo, *_rest, signed = synthetic
    pc4repo.effective_to = NOW - timedelta(seconds=1)
    assert client.get("/kernel/neutral/v1/tenants/7/branches/7/context",
                      headers=signed()).status_code == 403


def test_disabled_pc4_module_denies_403(synthetic):
    client, services, repo, pc4repo, *_rest, signed = synthetic
    pc4repo.allowed = False
    assert client.get("/kernel/neutral/v1/tenants/7/branches/7/context",
                      headers=signed()).status_code == 403


def test_pc5_pa_policy_is_separate_from_pc1(synthetic):
    client, services, repo, pc4repo, *_rest, signed = synthetic
    repo.role_assignments.clear()
    services.pc5.create_role(
        command_key="only-structural-role", role_code="n-structural-only",
        tenant_id=7, permissions=(STRUCTURE_PERMISSION,),
    )
    # A genuine PC5 assignment without PA read authority, not a forged role.
    identity_id = repo.sessions[SESSION].identity_id
    services.pc5.assign_role(
        command_key="only-structural-assignment",
        assignment=RoleAssignment(
            identity_id, 7, "n-structural-only",
            StructuralScope(ScopeType.TENANT, 7), NOW - timedelta(minutes=2),
        ),
    )
    assert client.get("/kernel/neutral/v1/tenants/7/branches/7/context",
                      headers=signed()).status_code == 200
    result = client.get("/kernel/neutral/v1/tenants/7/commercial-entitlements",
                        headers=signed())
    assert result.status_code == 403


def test_pk_invalid_pack_code_does_not_surface_secret(synthetic):
    client, *_rest, signed = synthetic
    result = client.get("/kernel/neutral/v1/tenants/7/packs/invalid%20%2F%20secret/state", headers=signed())
    assert result.status_code in (403, 404)
    assert "secret" not in result.text.lower()


def test_default_runtime_unconfigured_api_denies_without_bearer():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    result = client.get("/kernel/neutral/v1/tenants/7/branches/7/context")
    assert result.status_code == 401
    assert result.json()["detail"] == "NEUTRAL_BEARER_REQUIRED"


def test_frozen_startup_stays_unmodified_and_additive_candidate_exposes_routes():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    startup = (root / "startup.py").read_text(encoding="utf8")
    candidate = (root / "xcomp_neutral_d1_candidate.py").read_text(encoding="utf8")
    assert "neutral_d1_read_router" not in startup
    assert "init_database()" not in startup[startup.index("def create_app"):]
    assert "from startup import create_app" in candidate
    assert "app.include_router(neutral_d1_router)" in candidate
    assert "app = build_candidate_app()" in candidate


def test_only_get_and_no_mutating_routes():
    assert len(router.routes) == 3
    assert all(route.methods == {"GET"} for route in router.routes)

def test_separate_candidate_app_imports_and_exposes_three_get_routes_without_database_io():
    import os
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    env = {**os.environ,
           "DATABASE_URL": "postgresql://source-only:source-only@127.0.0.1:1/never_connect_source_only",
           "JWT_SECRET": "N-test-only-disposable-never-released-key-material-20261109",
           "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONUTF8": "1"}
    program = ("import xcomp_neutral_d1_candidate as c; "
               "from fastapi.testclient import TestClient; "
               "r=[x for x in c.app.routes if x.path.startswith('/kernel/neutral/v1/')]; "
               "assert len(r)==3 and all(x.methods=={'GET'} for x in r); "
               "assert TestClient(c.app).get('/kernel/neutral/v1/tenants/7/branches/7/context').status_code==401")
    result = subprocess.run(
        [sys.executable, "-c", program], cwd=str(root), env=env,
        capture_output=True, text=True, timeout=25,
    )
    assert result.returncode == 0, (result.stdout, result.stderr[-1200:])
