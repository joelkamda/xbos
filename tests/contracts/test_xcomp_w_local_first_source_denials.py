"""W contract-only acceptance tests pending PC0-approved restaurant module placement."""
from datetime import datetime,timedelta,timezone
import pytest
from core.platform.neutral_proof.deployment_profile import NodeScope,DeploymentProfile
from core.platform.neutral_proof.authority_epoch import AuthorityEpoch,AuthorityDenied
from core.platform.neutral_proof.local_pg17_unit_of_work import UnitOfWorkContext,admit_unit_of_work,TransactionDenied
from shared_operations.so8.finance_commit_receipt import FinanceCommitReceipt,require_local_cash_commit,require_provider_paid,FinanceDenied
NOW=datetime(2026,11,11,tzinfo=timezone.utc)
S=NodeScope(DeploymentProfile.LOCAL_SERVER,7,"node",11)
E=AuthorityEpoch(7,"node",4,NOW+timedelta(hours=1),"canonical_write",True)
def test_restaurant_local_shift_requires_real_pc5_and_one_writer():
 ctx=UnitOfWorkContext(S,"write",E,True)
 assert admit_unit_of_work(ctx,now=NOW,active_epoch=4,active_writer_node="node")==ctx
 with pytest.raises(TransactionDenied):
  admit_unit_of_work(UnitOfWorkContext(S,"write",E,False),now=NOW,
                     active_epoch=4,active_writer_node="node")
 with pytest.raises(AuthorityDenied):
  admit_unit_of_work(ctx,now=NOW,active_epoch=4,active_writer_node="other")
def test_w_cannot_label_uncommitted_provider_intent_as_paid():
 r=FinanceCommitReceipt(7,"node",4,"ledger-1",True,True)
 assert require_local_cash_commit(r,7,"node",4)==r
 with pytest.raises(FinanceDenied):require_provider_paid(r)
 with pytest.raises(FinanceDenied):require_local_cash_commit(r,8,"node",4)
