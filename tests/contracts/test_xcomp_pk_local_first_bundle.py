from dataclasses import replace
import pytest
from pack_platform.local_first_bundle_contracts import OfflinePackEnvelope
from pack_platform.local_first_bundle_verifier import require_pack,OfflinePackDenied
E=OfflinePackEnvelope(7,"restaurant",3,"cert-sha","publisher-A","node-A","issuer-1")
def test_same_pack_contract_cloud_and_local():
 assert require_pack(E,tenant_id=7,device_id="node-A",approved_pack="restaurant",minimum_version=3,publisher_chain_verified=True,certified=True,entitlement_admitted=True)==E
@pytest.mark.parametrize("override",[
 dict(publisher_chain_verified=False),dict(certified=False),dict(entitlement_admitted=False),
 dict(tenant_id=8),dict(device_id="other"),dict(approved_pack="wallet"),dict(minimum_version=4)
])
def test_invalid_publisher_entitlement_or_audience_denied(override):
 args=dict(tenant_id=7,device_id="node-A",approved_pack="restaurant",
           minimum_version=3,publisher_chain_verified=True,certified=True,entitlement_admitted=True)
 args.update(override)
 with pytest.raises(OfflinePackDenied):require_pack(E,**args)
