from dataclasses import replace
from datetime import datetime,timedelta,timezone
import pytest
from core.platform.neutral_proof.deployment_profile import NodeScope,DeploymentProfile
from core.platform.neutral_proof.authority_epoch import AuthorityEpoch,AuthorityDenied,require_writer
from core.platform.neutral_proof.local_pg17_unit_of_work import UnitOfWorkContext,admit_unit_of_work,TransactionDenied

NOW=datetime(2026,11,11,tzinfo=timezone.utc)
S=NodeScope(DeploymentProfile.LOCAL_SERVER,7,"local-A",11)
G=AuthorityEpoch(7,"local-A",3,NOW+timedelta(hours=1),"canonical_write",True)
def test_canonical_local_writer():
 assert require_writer(S,G,NOW,active_epoch=3,active_writer_node="local-A")==G
 assert admit_unit_of_work(UnitOfWorkContext(S,"write",G,True),now=NOW,active_epoch=3,active_writer_node="local-A").mode=="write"
@pytest.mark.parametrize("grant,epoch,writer",[
 (replace(G,signature_verified=False),3,"local-A"),
 (replace(G,revoked=True),3,"local-A"),
 (replace(G,tenant_id=8),3,"local-A"),
 (replace(G,node_id="local-B"),3,"local-A"),
 (replace(G,epoch=2),3,"local-A"),
 (replace(G,scope="read"),3,"local-A"),
 (replace(G,expires_at=NOW),3,"local-A"),
 (G,3,"local-B"),
])
def test_writer_fences_cross_tenant_expired_replay_and_split_brain(grant,epoch,writer):
 with pytest.raises(AuthorityDenied):
  require_writer(S,grant,NOW,active_epoch=epoch,active_writer_node=writer)
def test_session_required_even_for_read():
 with pytest.raises(TransactionDenied):
  admit_unit_of_work(UnitOfWorkContext(S,"read",None,False),now=NOW,active_epoch=3,active_writer_node="local-A")
