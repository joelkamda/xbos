"""Prospective offline shift intent; server policy injected, no DB side effects."""
from dataclasses import dataclass
from typing import Protocol
class ShiftDenied(PermissionError):pass
@dataclass(frozen=True)
class ShiftIntent:
    tenant_id:int
    branch_id:int
    session_id:str
    shift_code:str
    idempotency_key:str
class ShiftAuthority(Protocol):
    def require_writer(self,*,tenant_id:int,branch_id:int,session_id:str,action:str)->None:...
def admit_shift(intent:ShiftIntent, authority:ShiftAuthority):
    if not isinstance(intent,ShiftIntent) or not (intent.tenant_id>0 and intent.branch_id>0 and intent.session_id and intent.shift_code and intent.idempotency_key):
        raise ShiftDenied("SHIFT_SCOPE_OR_IDEMPOTENCY_DENIED")
    if not callable(getattr(authority,"require_writer",None)):
        raise ShiftDenied("TRUSTED_WRITER_PORT_REQUIRED")
    try:
        authority.require_writer(tenant_id=intent.tenant_id,branch_id=intent.branch_id,session_id=intent.session_id,action="restaurant.shift.write")
    except Exception as e:
        raise ShiftDenied("SHIFT_WRITER_DENIED") from e
    return intent
