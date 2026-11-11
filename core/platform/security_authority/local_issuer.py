"""Offline local session admission consumes PREISSUED verified delegation only.

A real identity verifier, hardware-sealed key and database persistence remain
independently gated. This does NOT mint or sign tokens.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

class ScopedNode(Protocol):
    tenant_id: int
    node_id: str

class LocalAuthorityDenied(ValueError): pass

@dataclass(frozen=True)
class PreissuedDelegation:
    tenant_id: int
    node_id: str
    permitted_role_codes: frozenset[str]
    expires_at: datetime
    verified_platform_issuer: bool
    revoked: bool = False

def permit_local_session(scope: ScopedNode, delegation: PreissuedDelegation,
                         role: str, now: datetime, *, active_membership: bool,
                         local_revoked: bool, device_verified: bool) -> bool:
    if not isinstance(delegation, PreissuedDelegation) or not delegation.verified_platform_issuer:
        raise LocalAuthorityDenied("PLATFORM_ISSUER_UNVERIFIED")
    if (delegation.revoked or not active_membership or local_revoked or not device_verified
        or delegation.tenant_id != scope.tenant_id or delegation.node_id != scope.node_id
        or role not in delegation.permitted_role_codes):
        raise LocalAuthorityDenied("LOCAL_PC5_DELEGATION_OR_MEMBERSHIP_DENIED")
    if (now.tzinfo is None or delegation.expires_at.tzinfo is None
        or now.astimezone(timezone.utc)>=delegation.expires_at.astimezone(timezone.utc)):
        raise LocalAuthorityDenied("DELEGATION_EXPIRED")
    return True
