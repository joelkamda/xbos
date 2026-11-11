"""PK immutable bundle envelope. No actual trust signatures issued."""
from dataclasses import dataclass

@dataclass(frozen=True)
class OfflinePackEnvelope:
    tenant_id: int
    pack_code: str
    version: int
    certified_fingerprint: str
    publisher_key_id: str
    device_id: str
    issuer_reference: str

    def __post_init__(self):
        if (self.tenant_id<=0 or not self.pack_code or self.version<=0
            or not self.certified_fingerprint or not self.publisher_key_id
            or not self.device_id or not self.issuer_reference):
            raise ValueError("INVALID_PACK_ENVELOPE")
