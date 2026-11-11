"""D1 neutral source-only read composition (PC1, PC4, PC5, PA, PK).

This module is *not* an operative merchant API. The production PC5/browser
session binding and PA/PK host adapters are intentionally NOT installed.
Tests can inject real domain services backed by disposable repositories.
No caller-supplied tenant, role, or PC5 session id is an authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from core.platform.operating_context import OperatingContextAuthority
from core.platform.security_authority import (
    AuthorizationRequest, Decision, ScopeType, SecurityAuthority, StructuralScope,
)
from core.platform.structure.service import StructuralAuthority, StructuralAuthorityError
from pack_platform.service import PackAuthority
from platform_admin.service import PlatformAdministrationAuthority

router = APIRouter(prefix="/kernel/neutral/v1", tags=["D1 neutral read candidate"])

STRUCTURE_PERMISSION = "pc1.structural.context.read"
PA_PERMISSION = "pa.commercial.entitlements.read"
PK_PERMISSION = "pk.pack.state.read"


@dataclass(frozen=True)
class BoundPC5Principal:
    """Created ONLY by a trusted server-side session-to-PC5 binding adapter."""
    session_id: UUID
    tenant_id: int
    branch_id: int


@dataclass(frozen=True)
class ServerVerifiedLocalNode:
    """Source-only proof projection from a future trusted LAN runtime.

    Never construct this from HTTP headers or browser-provided node identity.
    This type does not authorize a PC5 principal or install any dependency.
    """
    tenant_id: int
    branch_id: int
    node_id: str


def require_local_node_scope(
    binding: BoundPC5Principal,
    node: ServerVerifiedLocalNode | None,
) -> BoundPC5Principal:
    """Local read must bind verified PC5 context to verified server node.

    Does not grant access or replace the existing PC4/PC5 _admit policy.
    """
    if not isinstance(binding, BoundPC5Principal):
        raise HTTPException(status_code=401, detail="LOCAL_PC5_BINDING_ABSENT")
    if not isinstance(node, ServerVerifiedLocalNode) or not node.node_id.strip():
        raise HTTPException(status_code=503, detail="TRUSTED_LOCAL_NODE_NOT_ADMITTED")
    if (binding.tenant_id != node.tenant_id or
            binding.branch_id != node.branch_id):
        raise HTTPException(status_code=403, detail="LOCAL_NODE_TENANT_BRANCH_DENIED")
    return binding


@dataclass(frozen=True)
class NeutralReadServices:
    pc5: SecurityAuthority
    pc4: OperatingContextAuthority
    pc1: StructuralAuthority
    pa: PlatformAdministrationAuthority
    pk: PackAuthority
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)


def require_bearer_syntax(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer ") or not header[7:].strip():
        raise HTTPException(status_code=401, detail="NEUTRAL_BEARER_REQUIRED")
    return header[7:].strip()


def get_verified_pc5_binding(
    request: Request, token: str = Depends(require_bearer_syntax),
) -> BoundPC5Principal:
    """Deny until a separately verified, server-owned browser-to-PC5 bridge exists.

    The browser session table and PC5 sessions are distinct authorities.
    Caller headers, JWT roles, and an untrusted session UUID cannot substitute
    for the actual server-verified live PC5 binding.
    """
    raise HTTPException(
        status_code=503, detail="SERVER_BROWSER_TO_PC5_SESSION_BINDING_ABSENT",
    )


def get_neutral_read_services() -> NeutralReadServices:
    # No live PA/PK tenant gateway/readiness or PC5 binding is commissioned.
    raise HTTPException(status_code=503, detail="NEUTRAL_SERVICE_ADAPTERS_NOT_ADMITTED")


def _admit(
    binding: BoundPC5Principal, services: NeutralReadServices,
    tenant_id: int, permission: str, module: str, capability: str,
):
    if not isinstance(binding, BoundPC5Principal):
        raise HTTPException(status_code=401, detail="PC5_BINDING_NOT_VERIFIED")
    if binding.tenant_id != tenant_id or tenant_id <= 0:
        raise HTTPException(status_code=403, detail="TENANT_CONTEXT_MISMATCH")
    timestamp = services.clock()
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise HTTPException(status_code=503, detail="SERVER_CLOCK_UNTRUSTED")
    try:
        context = services.pc4.capability_context(
            tenant_id, module, capability, timestamp,
        )
        decision = services.pc5.authorize(AuthorizationRequest(
            session_id=binding.session_id,
            tenant_id=tenant_id,
            permission_code=permission,
            target_scope=StructuralScope(ScopeType.TENANT, tenant_id),
            resource_type="neutral_read",
            resource_id=capability,
            occurred_at=timestamp,
            module_available=context.module_available,
            module_enabled=context.module_enabled,
            entitled=context.entitled,
            feature_active=context.feature_active,
        ))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="PC4_OR_PC5_AUTHORITY_UNAVAILABLE") from exc
    if decision.decision is not Decision.ALLOW:
        raise HTTPException(status_code=403, detail="PC5_OR_PC4_POLICY_DENIED")


@router.get("/tenants/{tenant_id}/branches/{branch_id}/context")
def read_structural_context(
    tenant_id: int, branch_id: int,
    _bearer: str = Depends(require_bearer_syntax),
    binding: BoundPC5Principal = Depends(get_verified_pc5_binding),
    services: NeutralReadServices = Depends(get_neutral_read_services),
):
    if binding.branch_id != branch_id:
        raise HTTPException(status_code=403, detail="BRANCH_CONTEXT_MISMATCH")
    _admit(binding, services, tenant_id, STRUCTURE_PERMISSION,
           "platform.structure", "pc1.structural")
    try:
        result = services.pc1.resolve(
            tenant_id=tenant_id, legacy_branch_id=branch_id,
        )
    except StructuralAuthorityError as exc:
        raise HTTPException(status_code=403, detail="PC1_STRUCTURAL_SCOPE_DENIED") from exc
    return {
        "classification": "SOURCE_ONLY_NONOPERATIVE",
        "tenant_id": result.tenant.id,
        "branch_id": branch_id,
        "organization_unit_id": result.organization_unit.id,
        "location_id": result.location.id,
    }


@router.get("/tenants/{tenant_id}/commercial-entitlements")
def read_commercial_entitlements(
    tenant_id: int,
    _bearer: str = Depends(require_bearer_syntax),
    binding: BoundPC5Principal = Depends(get_verified_pc5_binding),
    services: NeutralReadServices = Depends(get_neutral_read_services),
):
    _admit(binding, services, tenant_id, PA_PERMISSION,
           "platform.administration", "pa.commercial")
    try:
        projected = services.pa.commercial_entitlement_projection(tenant_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="PA_READBACK_UNAVAILABLE") from exc
    return {
        "classification": "COMMERCIAL_PROJECTION_NOT_PC4_RUNTIME_ENTITLEMENT",
        "tenant_id": tenant_id, "projected_codes": list(projected),
        "operational": False,
    }


@router.get("/tenants/{tenant_id}/packs/{pack_code}/state")
def read_pack_state(
    tenant_id: int, pack_code: str,
    _bearer: str = Depends(require_bearer_syntax),
    binding: BoundPC5Principal = Depends(get_verified_pc5_binding),
    services: NeutralReadServices = Depends(get_neutral_read_services),
):
    _admit(binding, services, tenant_id, PK_PERMISSION,
           "pack.platform", "pk.pack.state")
    try:
        state = services.pk.state(tenant_id, pack_code)
    except Exception as exc:
        raise HTTPException(status_code=403, detail="PK_PACK_STATE_DENIED") from exc
    return {
        "classification": "READ_ONLY_PACK_STATE_NOT_ACTIVATION",
        "tenant_id": tenant_id, "pack_code": pack_code,
        "state": str(getattr(getattr(state, "status", None), "value",
                             getattr(state, "status", "not_installed"))) if state else "not_installed",
        "operational": False,
    }


# PCR V21 source-integration seam: not installed in production main:app.
# No authenticated live PC5/browser binding or PA/PK producer is available.
# A bearer is syntactically required; then the server-owned dependency
# remains fail-closed. No synthetic readiness response may become effective.
readiness_router = APIRouter(prefix="/platform/xcomp/d1d2", tags=["D1 D2 source-readiness candidate"])


@readiness_router.get("/readiness")
def nonoperative_readiness_candidate(
    _binding: BoundPC5Principal = Depends(get_verified_pc5_binding),
):
    raise HTTPException(status_code=503, detail="D1D2_TRUSTED_READINESS_COMPOSER_NOT_ADMITTED")
