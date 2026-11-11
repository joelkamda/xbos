"""Identical existing PK pack semantics in cloud and LAN-admitted local runtime."""
from dataclasses import replace
from pack_platform.local_first_bundle_contracts import OfflinePackEnvelope
from pack_platform.local_first_bundle_verifier import require_pack, OfflinePackDenied
from core.platform.neutral_proof.deployment_profile import DeploymentProfile
import pytest
E=OfflinePackEnvelope(7,"restaurant",3,"cert","publisher-A","node-A","platform-issuer")
def policy(profile,*,publisher_ok=True,tenant=7,entitled=True):
    assert profile in (DeploymentProfile.CLOUD,DeploymentProfile.LOCAL_SERVER)
    return require_pack(E,tenant_id=tenant,device_id="node-A",
                        approved_pack="restaurant",minimum_version=3,
                        publisher_chain_verified=publisher_ok,
                        certified=True,entitlement_admitted=entitled)
@pytest.mark.parametrize("profile",list(DeploymentProfile))
def test_cloud_local_pack_state_semantically_identical(profile):
    assert policy(profile)==E
@pytest.mark.parametrize("profile",list(DeploymentProfile))
@pytest.mark.parametrize("invalid",["issuer","tenant","lease"])
def test_cloud_local_same_denial(profile,invalid):
    with pytest.raises(OfflinePackDenied):
        policy(profile,publisher_ok=invalid!="issuer",
               tenant=8 if invalid=="tenant" else 7,
               entitled=invalid!="lease")
