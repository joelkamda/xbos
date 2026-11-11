"""SO8 detached intent: never canonical Finance truth."""
from dataclasses import dataclass

@dataclass(frozen=True)
class OfflineIntent:
    tenant_id: int
    device_id: str
    sequence: int
    source_id: str
    payload_hash: str
    state: str="PENDING_SERVER_VALIDATION"

    def __post_init__(self):
        if self.tenant_id<=0 or self.sequence<=0 or not self.device_id or not self.source_id:
            raise ValueError("UNSCOPED_INTENT")
        if self.state!="PENDING_SERVER_VALIDATION":
            raise ValueError("SO8_CANNOT_PRECOMMIT_FINANCE")
