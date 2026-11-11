"""Offline update admission must have rollback snapshot attestation."""
from core.platform.neutral_proof.offline_trust_bundle import require_bundle, PackageDenied

def admit_signed_update(bundle, *, tenant_id, node_id, current_release,
                        expected_digest, now, restore_rehearsal_passed):
    if not restore_rehearsal_passed:
        raise PackageDenied("NO_VERIFIED_ROLLBACK_SNAPSHOT")
    return require_bundle(bundle,tenant_id=tenant_id,node_id=node_id,
                          minimum_release=current_release+1,
                          expected_digest=expected_digest,now=now)
