"""Finance proof must originate from server committed ledger readback."""
from dataclasses import dataclass
class FinanceDenied(ValueError):pass

@dataclass(frozen=True)
class FinanceCommitReceipt:
    tenant_id: int
    node_id: str
    epoch: int
    ledger_id: str
    committed: bool
    readback_verified: bool
    provider_finality_verified: bool=False

def require_local_cash_commit(r:FinanceCommitReceipt,tenant_id:int,node_id:str,epoch:int):
    if (not isinstance(r,FinanceCommitReceipt) or not r.committed or not r.readback_verified
        or r.tenant_id!=tenant_id or r.node_id!=node_id or r.epoch!=epoch
        or not r.ledger_id):
        raise FinanceDenied("LEDGER_COMMIT_NOT_PROVEN")
    return r
def require_provider_paid(r:FinanceCommitReceipt):
    if not isinstance(r,FinanceCommitReceipt) or not r.provider_finality_verified:
        raise FinanceDenied("PROVIDER_FINALITY_ABSENT")
    return r
