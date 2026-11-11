"""Transaction admission only: does not open connections or write PostgreSQL."""
from dataclasses import dataclass
from typing import Protocol, Any
from datetime import datetime
from core.platform.neutral_proof.authority_epoch import AuthorityEpoch, require_writer
from core.platform.neutral_proof.deployment_profile import NodeScope

class TransactionDenied(ValueError): pass

class DBTransaction(Protocol):
    def execute(self, *args: Any, **kwargs: Any) -> Any: ...

@dataclass(frozen=True)
class UnitOfWorkContext:
    node: NodeScope
    mode: str
    authority: AuthorityEpoch | None
    tenant_session_verified: bool

def admit_unit_of_work(context: UnitOfWorkContext, *, now: datetime,
                       active_epoch: int, active_writer_node: str) -> UnitOfWorkContext:
    if not context.tenant_session_verified:
        raise TransactionDenied("PC5_SESSION_UNVERIFIED")
    if context.mode == "read":
        return context
    if context.mode != "write":
        raise TransactionDenied("UNKNOWN_TRANSACTION_MODE")
    require_writer(context.node, context.authority, now,
                   active_epoch=active_epoch, active_writer_node=active_writer_node)
    return context
