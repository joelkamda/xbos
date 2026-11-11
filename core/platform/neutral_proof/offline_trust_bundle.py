"""Signed installer trust boundary; signatures verified by independent caller."""
from dataclasses import dataclass
from datetime import datetime,timezone

class PackageDenied(ValueError):pass

@dataclass(frozen=True)
class PreverifiedOfflineBundle:
    publisher_signature_valid: bool
    tenant_id: int
    node_id: str
    release_version: int
    artifact_sha256: str
    expires_at: datetime
    trust_root_active: bool

def require_bundle(bundle: PreverifiedOfflineBundle, *, tenant_id: int,
                   node_id: str, minimum_release: int, expected_digest: str,
                   now: datetime) -> PreverifiedOfflineBundle:
    if not isinstance(bundle,PreverifiedOfflineBundle) or not bundle.publisher_signature_valid or not bundle.trust_root_active:
        raise PackageDenied("PUBLISHER_TRUST_DENIED")
    if bundle.tenant_id!=tenant_id or bundle.node_id!=node_id:
        raise PackageDenied("INSTALLER_AUDIENCE_MISMATCH")
    if bundle.release_version<minimum_release or bundle.release_version<=0:
        raise PackageDenied("INSTALLER_ROLLBACK_DENIED")
    if (len(expected_digest)!=64 or any(c not in "0123456789abcdef" for c in expected_digest.lower())
        or bundle.artifact_sha256.lower()!=expected_digest.lower()):
        raise PackageDenied("ARTIFACT_DIGEST_DENIED")
    if now.tzinfo is None or bundle.expires_at.tzinfo is None or now.astimezone(timezone.utc)>=bundle.expires_at.astimezone(timezone.utc):
        raise PackageDenied("INSTALLER_EXPIRED")
    return bundle
