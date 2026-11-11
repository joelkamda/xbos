"""Offline PC4 read-policy: never issues or renews platform licences."""
from dataclasses import dataclass
from datetime import datetime, timezone

class LeaseDenied(ValueError): pass

@dataclass(frozen=True)
class SignedEntitlementLease:
    tenant_id: int
    capability: str
    expires_at: datetime
    platform_signature_verified: bool
    locally_revoked: bool = False

def require_entitlement(lease: SignedEntitlementLease, tenant_id: int,
                        capability: str, now: datetime) -> SignedEntitlementLease:
    if not isinstance(lease,SignedEntitlementLease) or not lease.platform_signature_verified:
        raise LeaseDenied("UNVERIFIED_PLATFORM_ENTITLEMENT")
    if lease.locally_revoked or lease.tenant_id!=tenant_id or lease.capability!=capability:
        raise LeaseDenied("ENTITLEMENT_SCOPE_DENIED")
    if (now.tzinfo is None or lease.expires_at.tzinfo is None
        or now.astimezone(timezone.utc)>=lease.expires_at.astimezone(timezone.utc)):
        raise LeaseDenied("OFFLINE_ENTITLEMENT_EXPIRED")
    return lease
