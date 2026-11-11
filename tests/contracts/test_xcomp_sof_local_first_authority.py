import pytest
from shared_operations.so8.finance_commit_receipt import FinanceCommitReceipt,require_local_cash_commit,require_provider_paid,FinanceDenied
from shared_operations.so8.local_intent_envelope import OfflineIntent
def test_cash_commit_requires_real_readback_and_epoch():
 r=FinanceCommitReceipt(7,"node",4,"ledger-1",True,True)
 assert require_local_cash_commit(r,7,"node",4)==r
 with pytest.raises(FinanceDenied):require_provider_paid(r)
 for broken in [
  FinanceCommitReceipt(7,"node",4,"ledger-1",True,False),
  FinanceCommitReceipt(7,"node",4,"ledger-1",False,True),
  FinanceCommitReceipt(8,"node",4,"ledger-1",True,True)
 ]:
  with pytest.raises(FinanceDenied):require_local_cash_commit(broken,7,"node",4)
def test_so8_offline_intent_cannot_claim_paid_or_committed():
 with pytest.raises(ValueError):OfflineIntent(7,"device",1,"event-1","a"*64,state="PAID")
 assert OfflineIntent(7,"device",1,"event-1","a"*64).state=="PENDING_SERVER_VALIDATION"
