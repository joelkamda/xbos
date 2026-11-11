from dataclasses import replace
from datetime import datetime,timedelta,timezone
import pytest
from core.platform.neutral_proof.deployment_profile import NodeScope,DeploymentProfile
from core.platform.security_authority.local_issuer import PreissuedDelegation,permit_local_session,LocalAuthorityDenied
from core.platform.operating_context.signed_entitlement_lease import SignedEntitlementLease,require_entitlement,LeaseDenied
NOW=datetime(2026,11,11,tzinfo=timezone.utc)
S=NodeScope(DeploymentProfile.LOCAL_SERVER,7,"A",11)
D=PreissuedDelegation(7,"A",frozenset(["cashier","manager"]),NOW+timedelta(hours=4),True)
def test_signed_delegation_and_local_membership():
 assert permit_local_session(S,D,"cashier",NOW,active_membership=True,local_revoked=False,device_verified=True)
@pytest.mark.parametrize("delegation,role,active,revoked,device",[
 (replace(D,verified_platform_issuer=False),"cashier",True,False,True),
 (replace(D,tenant_id=8),"cashier",True,False,True),
 (replace(D,node_id="B"),"cashier",True,False,True),
 (replace(D,expires_at=NOW),"cashier",True,False,True),
 (D,"platform_license_issuer",True,False,True),
 (D,"cashier",False,False,True),
 (D,"cashier",True,True,True),
 (D,"cashier",True,False,False),
])
def test_offline_cannot_mint_or_restore_revoked_authority(delegation,role,active,revoked,device):
 with pytest.raises(LocalAuthorityDenied):
  permit_local_session(S,delegation,role,NOW,active_membership=active,local_revoked=revoked,device_verified=device)
def test_entitlement_requires_real_platform_preissue():
 l=SignedEntitlementLease(7,"cash_pos",NOW+timedelta(hours=2),True)
 assert require_entitlement(l,7,"cash_pos",NOW)==l
 for bad in [replace(l,platform_signature_verified=False),replace(l,locally_revoked=True),
             replace(l,tenant_id=8),replace(l,expires_at=NOW)]:
  with pytest.raises(LeaseDenied):require_entitlement(bad,7,"cash_pos",NOW)

def test_shared_d1_local_read_requires_preissued_delegation_and_lease():
 from uuid import uuid4
 from platform_admin.neutral_d1_read_router import (
     BoundPC5Principal, ServerVerifiedLocalNode, require_local_node_scope,
 )
 from platform_admin.neutral_d1_pc5_binding_verifier import (
     verify_local_delegated_read, PC5BindingDenied,
 )
 from fastapi import HTTPException
 principal=BoundPC5Principal(uuid4(),7,11)
 verified_node=ServerVerifiedLocalNode(7,11,"A")
 assert require_local_node_scope(principal,verified_node)==principal
 with pytest.raises(HTTPException) as mismatch:
  require_local_node_scope(principal,ServerVerifiedLocalNode(8,11,"A"))
 assert mismatch.value.status_code==403
 lease=SignedEntitlementLease(7,"neutral_read",NOW+timedelta(hours=1),True)
 kwargs=dict(scope=S,
  read_delegation=lambda sid:D,
  read_role=lambda sid:"cashier",
  read_membership_active=lambda sid:True,
  read_locally_revoked=lambda sid:False,
  read_device_verified=lambda sid:True,
  read_signed_lease=lambda tenant:lease,
  clock=lambda:NOW)
 assert verify_local_delegated_read(principal,**kwargs)==principal
 with pytest.raises(PC5BindingDenied):
  verify_local_delegated_read(principal,**{**kwargs,"read_locally_revoked":lambda sid:True})
 with pytest.raises(PC5BindingDenied):
  verify_local_delegated_read(principal,**{**kwargs,"read_signed_lease":lambda tenant:replace(lease,platform_signature_verified=False)})
 with pytest.raises(PC5BindingDenied):
  verify_local_delegated_read(principal,**{**kwargs,"read_role":lambda sid:"platform_issuer"})
