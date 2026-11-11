from dataclasses import replace
from datetime import datetime,timedelta,timezone
import pytest
from core.platform.neutral_proof.offline_trust_bundle import PreverifiedOfflineBundle,require_bundle,PackageDenied
from core.platform.neutral_proof.signed_update_admission import admit_signed_update
from core.platform.neutral_proof.backup_recovery import RestoreAttestation,admit_replacement
from core.platform.neutral_proof.authority_epoch import AuthorityDenied
from core.platform.security_authority.clock_rollback_guard import require_monotonic_wallclock,ClockDenied
NOW=datetime(2026,11,11,tzinfo=timezone.utc)
B=PreverifiedOfflineBundle(True,7,"node-A",4,"a"*64,NOW+timedelta(days=2),True)
def test_bundle_and_signed_update_require_prior_verified_restore():
 assert require_bundle(B,tenant_id=7,node_id="node-A",minimum_release=4,expected_digest="a"*64,now=NOW)==B
 assert admit_signed_update(B,tenant_id=7,node_id="node-A",current_release=3,expected_digest="a"*64,now=NOW,restore_rehearsal_passed=True)==B
 with pytest.raises(PackageDenied):admit_signed_update(B,tenant_id=7,node_id="node-A",current_release=3,expected_digest="a"*64,now=NOW,restore_rehearsal_passed=False)
@pytest.mark.parametrize("bundle",[
 replace(B,publisher_signature_valid=False),replace(B,tenant_id=8),
 replace(B,node_id="attacker"),replace(B,trust_root_active=False),
 replace(B,release_version=2),replace(B,expires_at=NOW),
])
def test_bundle_fails_closed(bundle):
 with pytest.raises(PackageDenied):
  require_bundle(bundle,tenant_id=7,node_id="node-A",minimum_release=4,expected_digest="a"*64,now=NOW)
def test_restored_node_must_fence_old_epoch():
 a=RestoreAttestation(7,"old","new",2,3,True,True,True)
 assert admit_replacement(a)==a
 with pytest.raises(AuthorityDenied):admit_replacement(replace(a,prior_node_fenced=False))
 with pytest.raises(AuthorityDenied):admit_replacement(replace(a,new_epoch=2))
def test_clock_rollback_denied():
 with pytest.raises(ClockDenied):
  require_monotonic_wallclock(NOW-timedelta(hours=1),NOW)
