"""Signed envelope admission; replay map is provided by trusted durable ledger."""
from dataclasses import dataclass
from core.platform.neutral_proof.authority_epoch import AuthorityDenied

@dataclass(frozen=True)
class SyncEnvelope:
    tenant_id: int
    node_id: str
    epoch: int
    sequence: int
    source_id: str
    payload_sha256: str
    signature_verified: bool

def admit_sync(e: SyncEnvelope, *, tenant_id: int, known_epoch: int,
               known_records: dict[str,str]):
    if (not isinstance(e,SyncEnvelope) or not e.signature_verified or e.tenant_id!=tenant_id
        or e.epoch!=known_epoch or e.sequence<=0 or not e.source_id
        or len(e.payload_sha256)!=64
        or any(c not in "0123456789abcdef" for c in e.payload_sha256.lower())):
        raise AuthorityDenied("SIGNED_SYNC_CONTEXT_DENIED")
    if e.source_id in known_records:
        if known_records[e.source_id]!=e.payload_sha256:
            raise AuthorityDenied("SIGNED_SYNC_HASH_CONFLICT")
        return "DUPLICATE_NO_EFFECT"
    return "NEW_PENDING_DURABLE_INSERT"
