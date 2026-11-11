"""Prospective receipt labeling requires durable server ledger confirmation."""
from dataclasses import dataclass
class ReceiptDenied(PermissionError):pass
@dataclass(frozen=True)
class FinanceReadback:
    tenant_id:int
    branch_id:int
    node_id:str
    epoch:int
    ledger_ref:str
    committed:bool
    readback_verified:bool
    provider_finality_verified:bool=False
def cash_receipt(v:FinanceReadback,*,tenant_id:int,branch_id:int,node_id:str,epoch:int):
    if not isinstance(v,FinanceReadback) or not all((
        v.committed,v.readback_verified,v.tenant_id==tenant_id,
        v.branch_id==branch_id,v.node_id==node_id,v.epoch==epoch,
        v.epoch>0,v.ledger_ref)):
        raise ReceiptDenied("DURABLE_CASH_PROOF_REQUIRED")
    return f"LOCAL CASH COMMITTED {v.ledger_ref} EPOCH {epoch}"
def provider_paid(v:FinanceReadback):
    if not isinstance(v,FinanceReadback) or not v.provider_finality_verified:
        raise ReceiptDenied("PROVIDER_FINALITY_ABSENT")
    return v.ledger_ref
