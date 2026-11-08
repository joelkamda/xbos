"""Wave1 N: disposable TestClient PC1/PC4/PC5 integration proof only.

This is NOT installed in main:app and is NOT a merchant-hosted HTTP API.
Uses actual domain services with synthetic in-memory repository fixtures.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from uuid import UUID

import jwt
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from core.platform.structure.service import StructuralAuthority, StructuralAuthorityError
from core.platform.operating_context import (
    CapabilityContext, GrantEntitlement, OperatingContextAuthority,
)
from core.platform.security_authority import (
    AuthorizationRequest, Decision, PermissionDefinition, RoleAssignment,
    ScopeType, StructuralScope,
)
from tests.contracts.test_pc1_structural_authority import MemoryRepository as PC1MemoryRepository
from tests.contracts.test_pc5_identity_policy_audit import configured, NOW, SESSION


TEST_KEY = "xcomp-wave1-synthetic-only-unpublished-test-key"
TEST_PERMISSION = "pc1.structural.context.read"
TEST_CAPABILITY = "pc1.structural"


class SyntheticEffectivePC4Repository:
    """Disposable repository explicitly enforcing as-of grant intervals."""

    def __init__(self):
        self.grants = []
        self.module_enabled = True

    def grant_entitlement(self, command, fingerprint):
        self.grants.append(command)
        return command

    def capability_context(self, tenant_id, module_code, capability_code, as_of):
        effective = any(
            grant.tenant_id == tenant_id
            and grant.capability_code == capability_code
            and grant.effective_from <= as_of
            and (grant.effective_to is None or as_of < grant.effective_to)
            for grant in self.grants
        )
        return CapabilityContext(
            module_available=(module_code == "platform.structure"),
            module_enabled=self.module_enabled,
            entitled=effective,
            feature_active=True,
            permission_authorized=None,
        )


@pytest.fixture()
def sandbox():
    pc5, security_repository, identity = configured()
    pc5.register_permission(
        command_key="n-d1-permission",
        definition=PermissionDefinition(
            TEST_PERMISSION, "pc1", "structural_context", "read",
            allowed_scopes=(ScopeType.TENANT,),
        ),
    )
    pc5.create_role(
        command_key="n-d1-role", role_code="n_structural_viewer",
        tenant_id=7, permissions=(TEST_PERMISSION,),
    )
    pc5.assign_role(
        command_key="n-d1-assignment",
        assignment=RoleAssignment(
            identity.id, 7, "n_structural_viewer",
            StructuralScope(ScopeType.TENANT, 7), NOW - timedelta(days=1),
        ),
    )

    structure_repository = PC1MemoryRepository()
    structure_repository.tenants[7] = replace(
        structure_repository.tenants.pop(1), id=7
    )
    for table in (
        structure_repository.organizations,
        structure_repository.legals,
        structure_repository.places,
    ):
        for (tenant_id, object_id), item in list(table.items()):
            if tenant_id == 1:
                del table[(tenant_id, object_id)]
                table[(7, object_id)] = replace(item, tenant_id=7)
    structure_repository.mappings = {(7, 7): (11, 200)}
    pc1 = StructuralAuthority(structure_repository)

    cap_repository = SyntheticEffectivePC4Repository()
    pc4 = OperatingContextAuthority(cap_repository)
    pc4.grant_entitlement(
        GrantEntitlement(
            command_key="n-d1-entitlement",
            tenant_id=7,
            capability_code=TEST_CAPABILITY,
            effective_from=NOW - timedelta(minutes=10),
            effective_to=NOW + timedelta(minutes=10),
        )
    )

    state = {"now": NOW}
    app = FastAPI()

    @app.get("/test-only/n/v1/tenants/{tenant_id}/branches/{branch_id}")
    def structural_context(tenant_id: int, branch_id: int, request: Request):
        authorization = request.headers.get("Authorization") or ""
        if not authorization.startswith("Bearer "):
            raise HTTPException(401, "UNAUTHENTICATED")
        try:
            claims = jwt.decode(
                authorization[7:], TEST_KEY, algorithms=["HS256"]
            )
            session_id = UUID(str(claims["sid"]))
        except (jwt.PyJWTError, ValueError, KeyError, TypeError):
            raise HTTPException(401, "UNAUTHENTICATED") from None

        # A signed claim is not a PC5 role or current-session authorization.
        if claims.get("tenant_id") != tenant_id:
            raise HTTPException(403, "TENANT_CONTEXT_MISMATCH")
        capability = pc4.capability_context(
            tenant_id, "platform.structure", TEST_CAPABILITY, state["now"],
        )
        decision = pc5.authorize(
            AuthorizationRequest(
                session_id=session_id,
                permission_code=TEST_PERMISSION,
                tenant_id=tenant_id,
                target_scope=StructuralScope(ScopeType.TENANT, tenant_id),
                resource_type="structural_context",
                resource_id=str(branch_id),
                occurred_at=state["now"],
                module_available=capability.module_available,
                module_enabled=capability.module_enabled,
                entitled=capability.entitled,
                feature_active=capability.feature_active,
            )
        )
        if decision.decision is not Decision.ALLOW:
            raise HTTPException(403, "AUTHORITY_DENIED")

        try:
            result = pc1.resolve(
                tenant_id=tenant_id, legacy_branch_id=branch_id
            )
        except StructuralAuthorityError:
            raise HTTPException(403, "STRUCTURAL_SCOPE_DENIED") from None
        return {
            "tenant_id": result.tenant.id,
            "organization_unit_id": result.organization_unit.id,
            "location_id": result.location.id,
            "legacy_branch_id": branch_id,
        }

    def signed(role="reader", tenant_id=7, key=TEST_KEY):
        payload = {
            "sid": str(SESSION),
            "tenant_id": tenant_id,
            "role": role,
        }
        return {"Authorization": "Bearer " + jwt.encode(
            payload, key, algorithm="HS256"
        )}

    return TestClient(app), pc5, security_repository, cap_repository, state, signed


def test_positive_authorized_tenant_branch_readback(sandbox):
    client, *_rest, signed = sandbox
    response = client.get("/test-only/n/v1/tenants/7/branches/7", headers=signed())
    assert response.status_code == 200
    assert response.json() == {
        "tenant_id": 7,
        "organization_unit_id": 11,
        "location_id": 200,
        "legacy_branch_id": 7,
    }


def test_missing_bearer_denies_401(sandbox):
    client = sandbox[0]
    assert client.get("/test-only/n/v1/tenants/7/branches/7").status_code == 401


def test_wrong_signed_token_key_denies_401(sandbox):
    client, *_rest, signed = sandbox
    assert client.get(
        "/test-only/n/v1/tenants/7/branches/7",
        headers=signed(key="wrong-synthetic-only-key")
    ).status_code == 401


def test_wrong_tenant_denies_403(sandbox):
    client, *_rest, signed = sandbox
    assert client.get(
        "/test-only/n/v1/tenants/8/branches/7",
        headers=signed()
    ).status_code == 403


def test_wrong_branch_denies_403(sandbox):
    client, *_rest, signed = sandbox
    assert client.get(
        "/test-only/n/v1/tenants/7/branches/99",
        headers=signed()
    ).status_code == 403


def test_forged_platform_admin_role_never_grants_permission(sandbox):
    client, _pc5, security_repository, _pc4, _state, signed = sandbox
    security_repository.role_assignments.clear()
    assert client.get(
        "/test-only/n/v1/tenants/7/branches/7",
        headers=signed(role="platform_admin")
    ).status_code == 403


def test_revoked_pc5_session_denies_403(sandbox):
    client, pc5, _repo, _pc4, _state, signed = sandbox
    pc5.revoke_session(SESSION, NOW)
    assert client.get(
        "/test-only/n/v1/tenants/7/branches/7",
        headers=signed()
    ).status_code == 403


def test_expired_pc5_session_denies_403(sandbox):
    client, _pc5, repo, _pc4, _state, signed = sandbox
    repo.sessions[SESSION] = replace(repo.sessions[SESSION], expires_at=NOW)
    assert client.get(
        "/test-only/n/v1/tenants/7/branches/7",
        headers=signed()
    ).status_code == 403


def test_expired_pc4_entitlement_denies_403(sandbox):
    client, _pc5, _repo, _pc4, state, signed = sandbox
    state["now"] = NOW + timedelta(minutes=20)
    assert client.get(
        "/test-only/n/v1/tenants/7/branches/7",
        headers=signed()
    ).status_code == 403


def test_disabled_pc4_module_denies_403(sandbox):
    client, _pc5, _repo, pc4_repo, _state, signed = sandbox
    pc4_repo.module_enabled = False
    assert client.get(
        "/test-only/n/v1/tenants/7/branches/7",
        headers=signed()
    ).status_code == 403


def test_tenant_branch_headers_cannot_override_signed_and_server_context(sandbox):
    client, *_rest, signed = sandbox
    headers = {
        **signed(),
        "X-Tenant-Code": "attacker-tenant",
        "X-Branch-Code": "attacker-branch",
    }
    result = client.get("/test-only/n/v1/tenants/7/branches/7", headers=headers)
    assert result.status_code == 200
    assert result.json()["tenant_id"] == 7
