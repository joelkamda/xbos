"""Pure restore authorization. Real backup and device fencing are separate."""
from dataclasses import dataclass
from core.platform.neutral_proof.authority_epoch import AuthorityDenied

@dataclass(frozen=True)
class RestoreAttestation:
    tenant_id: int
    old_node: str
    new_node: str
    previous_epoch: int
    new_epoch: int
    backup_digest_verified: bool
    quorum_authorized: bool
    prior_node_fenced: bool

def admit_replacement(a: RestoreAttestation):
    if (not isinstance(a,RestoreAttestation) or not a.backup_digest_verified
        or not a.quorum_authorized or not a.prior_node_fenced
        or a.old_node==a.new_node or a.new_epoch<=a.previous_epoch or a.previous_epoch<1):
        raise AuthorityDenied("RESTORE_OR_DEVICE_FENCING_UNPROVEN")
    return a
