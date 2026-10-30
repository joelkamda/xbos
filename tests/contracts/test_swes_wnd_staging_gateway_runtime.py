"""Bounded SWES B2 startup-composition tests: no network, DB or provider calls."""
from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID

import pytest

from core.integrations.xafpay_v2.client import XafPayV2Client
from restaurant.customer_channel.gateway_checkout_bridge import (
    VerifiedGatewayMerchantBinding,
)
from restaurant.customer_channel.swes_staging_checkout_runtime import (
    TrustedStagingCheckoutAdmission,
    install_staging_checkout_runtime,
)

SHA = "a" * 40


def environment(**overrides):
    result = {
        "RENDER": "true",
        "RENDER_SERVICE_ID": "srv-db3vej67bikc73ai2080",
        "RENDER_SERVICE_TYPE": "web",
        "RENDER_EXTERNAL_HOSTNAME": "wnd-xafpay-demo-austin-backend.onrender.com",
        "RENDER_GIT_BRANCH": "compat/wnd-demo-cc-r1-legacy-neutral-bridge",
        "RENDER_GIT_COMMIT": SHA,
        "XAFPAY_SWES_WND_CHECKOUT_TEST_ENABLED": "1",
    }
    result.update(overrides)
    return result


def admission(**changes):
    data = {
        "binding": VerifiedGatewayMerchantBinding(
            tenant_id=910001,
            merchant_public_id=UUID("20000000-0000-4000-8000-000000000102"),
            gateway_merchant_id="mch_swes_demo_only",
            service_credential_reference="opaque-swes-only",
        ),
        "client": XafPayV2Client(
            "https://xafpay-gateway-staging.onrender.com", "xps_synthetic.not-a-secret"
        ),
        "render_database_id": "dpg-db3rd17lk1mc73ckrie0-a",
        "deployed_source_sha": SHA,
        "isolated_synthetic_tenant_proven": True,
        "authenticated_service_checkout_scope_proven": True,
        "sandbox_provider_only_proven": True,
    }
    data.update(changes)
    return TrustedStagingCheckoutAdmission(**data)


def app():
    return SimpleNamespace(state=SimpleNamespace())


def test_disabled_default_never_installs_runtime():
    target = app()
    assert not install_staging_checkout_runtime(target, admission=admission(), environ={})
    assert not hasattr(target.state, "wnd_gateway_checkout_runtime")


@pytest.mark.parametrize("changes", [
    {"RENDER": "false"},
    {"RENDER_GIT_BRANCH": "main"},
    {"RENDER_SERVICE_ID": "other"},
    {"RENDER_EXTERNAL_HOSTNAME": "production.example"},
])
def test_wrong_deploy_context_holds(changes):
    with pytest.raises(RuntimeError, match="CONTEXT_HOLD"):
        install_staging_checkout_runtime(app(), admission=admission(), environ=environment(**changes))


def test_missing_admission_fails_closed():
    with pytest.raises(TypeError, match="ADMISSION_REQUIRED"):
        install_staging_checkout_runtime(app(), admission=None, environ=environment())


@pytest.mark.parametrize("changes,reason", [
    ({"render_database_id": "other"}, "DATABASE_HOLD"),
    ({"deployed_source_sha": "b"*40}, "SOURCE_PIN_HOLD"),
    ({"isolated_synthetic_tenant_proven": False}, "PROTECTED_PROOF_HOLD"),
    ({"authenticated_service_checkout_scope_proven": False}, "PROTECTED_PROOF_HOLD"),
    ({"sandbox_provider_only_proven": False}, "PROTECTED_PROOF_HOLD"),
])
def test_missing_private_evidence_holds(changes, reason):
    with pytest.raises(RuntimeError, match=reason):
        install_staging_checkout_runtime(app(), admission=admission(**changes), environ=environment())


def test_physical_wnd_tenant_rejected():
    wrong = admission()
    binding = replace(wrong.binding, tenant_id=2)
    with pytest.raises(RuntimeError, match="BINDING_HOLD"):
        install_staging_checkout_runtime(app(), admission=replace(wrong, binding=binding), environ=environment())


def test_non_sandbox_gateway_url_rejected():
    wrong = admission(client=XafPayV2Client("https://gateway.example.com", "xps_fake.nonsecret"))
    with pytest.raises(RuntimeError, match="BINDING_HOLD"):
        install_staging_checkout_runtime(app(), admission=wrong, environ=environment())


def test_exact_private_admission_wires_once():
    target = app()
    proof = admission()
    assert install_staging_checkout_runtime(target, admission=proof, environ=environment())
    assert target.state.wnd_gateway_checkout_runtime.binding is proof.binding
    assert target.state.wnd_gateway_checkout_runtime.client is proof.client
    with pytest.raises(RuntimeError, match="ALREADY_BOUND"):
        install_staging_checkout_runtime(target, admission=proof, environ=environment())
