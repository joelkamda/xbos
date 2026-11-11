"""No replay can convert intent to a settled Finance entry."""
from shared_operations.so8.finance_commit_receipt import FinanceDenied
def require_new_finance_source(source_id:str,payload_hash:str,existing:dict[str,str]):
    if not source_id or len(payload_hash)!=64:
        raise FinanceDenied("INVALID_FINANCE_IDEMPOTENCY")
    if source_id in existing:
        if existing[source_id]!=payload_hash:
            raise FinanceDenied("DUPLICATE_SOURCE_CONFLICT")
        return "DUPLICATE_NO_POSTING"
    return "NEW_NEEDS_AUTHORIZED_LEDGER_TRANSACTION"
