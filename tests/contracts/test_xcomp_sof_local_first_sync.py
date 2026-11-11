import pytest
from core.platform.neutral_proof.node_sync_envelope import SyncEnvelope,admit_sync
from core.platform.neutral_proof.authority_epoch import AuthorityDenied
from shared_operations.so8.offline_finance_replay_guard import require_new_finance_source,FinanceDenied
from shared_operations.so8.signed_node_sync_envelope import qualify_finance_sync
E=SyncEnvelope(7,"node",4,1,"sale-1","a"*64,True)
def test_signed_sync_replay_no_double_posting():
 assert qualify_finance_sync(E,tenant_id=7,epoch=4,seen={},trusted_node_validator=admit_sync)=="NEW_PENDING_DURABLE_INSERT"
 assert qualify_finance_sync(E,tenant_id=7,epoch=4,seen={"sale-1":"a"*64},trusted_node_validator=admit_sync)=="DUPLICATE_NO_EFFECT"
 assert require_new_finance_source("sale-1","a"*64,{"sale-1":"a"*64})=="DUPLICATE_NO_POSTING"
def test_conflicting_replay_rejected():
 with pytest.raises(AuthorityDenied):
  qualify_finance_sync(E,tenant_id=7,epoch=4,seen={"sale-1":"b"*64},trusted_node_validator=admit_sync)
 with pytest.raises(AuthorityDenied):
  qualify_finance_sync(E,tenant_id=8,epoch=4,seen={},trusted_node_validator=admit_sync)
 with pytest.raises(FinanceDenied):
  require_new_finance_source("sale-1","b"*64,{"sale-1":"a"*64})
