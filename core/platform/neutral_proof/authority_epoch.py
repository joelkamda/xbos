"""Fail-closed single-writer epoch check: no network or key issuance."""
from dataclasses import dataclass
from datetime import datetime, timezone
from core.platform.neutral_proof.deployment_profile import NodeScope

class AuthorityDenied(ValueError): pass

@dataclass(frozen=True)
class AuthorityEpoch:
    tenant_id: int
    node_id: str
    epoch: int
    expires_at: datetime
    scope: str
    signature_verified: bool
    revoked: bool = False

def _utc(dt):
    if not isinstance(dt, datetime) or dt.tzinfo is None or dt.utcoffset() is None:
        raise AuthorityDenied("TRUSTED_TIME_REQUIRED")
    return dt.astimezone(timezone.utc)

def require_writer(scope: NodeScope, grant: AuthorityEpoch | None, now: datetime,
                   *, active_epoch: int, active_writer_node: str) -> AuthorityEpoch:
    if not isinstance(grant, AuthorityEpoch) or not grant.signature_verified or grant.revoked:
        raise AuthorityDenied("NO_VERIFIED_ACTIVE_EPOCH")
    if (grant.tenant_id != scope.tenant_id or grant.node_id != scope.node_id
        or active_writer_node != scope.node_id or grant.epoch != active_epoch or grant.epoch <= 0
        or grant.scope != "canonical_write"):
        raise AuthorityDenied("TENANT_NODE_EPOCH_FENCED")
    if _utc(grant.expires_at) <= _utc(now):
        raise AuthorityDenied("WRITER_LEASE_EXPIRED")
    return grant
