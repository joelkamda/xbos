"""PK rejects unverified publisher, tenant, entitlement, certification."""
from pack_platform.local_first_bundle_contracts import OfflinePackEnvelope
class OfflinePackDenied(ValueError): pass

def require_pack(envelope: OfflinePackEnvelope, *, tenant_id: int, device_id: str,
                 approved_pack: str, minimum_version: int,
                 publisher_chain_verified: bool, certified: bool,
                 entitlement_admitted: bool) -> OfflinePackEnvelope:
    if not isinstance(envelope,OfflinePackEnvelope):
        raise OfflinePackDenied("PACK_CONTRACT_MISSING")
    if not publisher_chain_verified or not certified or not entitlement_admitted:
        raise OfflinePackDenied("PACK_PLATFORM_AUTHORITY_UNVERIFIED")
    if (envelope.tenant_id!=tenant_id or envelope.device_id!=device_id
        or envelope.pack_code!=approved_pack or envelope.version<minimum_version):
        raise OfflinePackDenied("PACK_AUDIENCE_OR_VERSION_DENIED")
    return envelope
