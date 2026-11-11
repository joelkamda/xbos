"""No unsigned/offline package may bypass install rollback or tenancy."""
from dataclasses import replace
from datetime import datetime,timedelta,timezone
import pytest
from core.platform.neutral_proof.offline_trust_bundle import PreverifiedOfflineBundle,PackageDenied
from core.platform.neutral_proof.signed_update_admission import admit_signed_update
from core.platform.neutral_proof.backup_recovery import RestoreAttestation,admit_replacement
from core.platform.neutral_proof.authority_epoch import AuthorityDenied
NOW=datetime(2026,11,11,tzinfo=timezone.utc)
B=PreverifiedOfflineBundle(True,7,"node-A",4,"a"*64,NOW+timedelta(hours=1),True)
def valid(**kw):
 return admit_signed_update(B,tenant_id=7,node_id="node-A",
        current_release=3,expected_digest="a"*64,
        now=NOW,restore_rehearsal_passed=True,**kw)
def test_rollback_snapshot_mandatory():
 with pytest.raises(PackageDenied):
  admit_signed_update(B,tenant_id=7,node_id="node-A",
      current_release=3,expected_digest="a"*64,
      now=NOW,restore_rehearsal_passed=False)
@pytest.mark.parametrize("b",[
 replace(B,publisher_signature_valid=False),
 replace(B,trust_root_active=False),
 replace(B,tenant_id=8),
 replace(B,node_id="other"),
 replace(B,release_version=3),
 replace(B,expires_at=NOW)])
def test_wrong_audience_old_or_unsigned_package_denied(b):
 with pytest.raises(PackageDenied):
  admit_signed_update(b,tenant_id=7,node_id="node-A",
      current_release=3,expected_digest="a"*64,
      now=NOW,restore_rehearsal_passed=True)
def test_recovery_old_node_fencing_mandatory():
 r=RestoreAttestation(7,"old","new",3,4,True,True,True)
 assert admit_replacement(r)==r
 with pytest.raises(AuthorityDenied):
  admit_replacement(replace(r,prior_node_fenced=False))
