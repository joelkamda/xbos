"""SOF consumes N-owned validator through a trusted composition port.

PC0 does not authorize communications importing neutral_proof directly.
"""
from typing import Callable, Any

def qualify_finance_sync(envelope: Any, *, tenant_id: int, epoch: int,
                         seen: dict[str,str], trusted_node_validator: Callable):
    if not callable(trusted_node_validator):
        raise ValueError("NODE_EPOCH_VERIFIER_REQUIRED")
    return trusted_node_validator(envelope, tenant_id=tenant_id,
                                  known_epoch=epoch, known_records=seen)
