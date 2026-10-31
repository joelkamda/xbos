"""SWES B2: explicit, default-off TEST checkout runtime installation.

A trusted application composition caller must supply independently established
B1 evidence. Environment variables alone must never invent merchant ownership
or provide an admission token.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import SimpleNamespace
from uuid import UUID

from core.integrations.xafpay_v2.client import XafPayV2Client

from .gateway_checkout_bridge import VerifiedGatewayMerchantBinding

_SERVICE = "srv-db3vej67bikc73ai2080"
_HOST = "wnd-xafpay-demo-austin-backend.onrender.com"
_BRANCH = "compat/wnd-demo-cc-r1-legacy-neutral-bridge"
_DATABASE = "dpg-db3rd17lk1mc73ckrie0-a"
_GATEWAY = "https://xafpay-gateway-staging.onrender.com"
_TEST_TENANT = 910001
_TEST_MERCHANT = UUID("4b196022-65a1-548c-b122-f1f9e4b78bea")
_FLAG = "XAFPAY_SWES_WND_CHECKOUT_TEST_ENABLED"


@dataclass(frozen=True, slots=True)
class TrustedStagingCheckoutAdmission:
    """Source-independent private operator evidence; never a credential value."""

    binding: VerifiedGatewayMerchantBinding
    client: XafPayV2Client
    render_database_id: str
    deployed_source_sha: str
    isolated_synthetic_tenant_proven: bool
    authenticated_service_checkout_scope_proven: bool
    sandbox_provider_only_proven: bool


def install_staging_checkout_runtime(
    app,
    *,
    admission: TrustedStagingCheckoutAdmission | None,
    environ: Mapping[str, str],
) -> bool:
    """Never construct a binding or credential from request/environment alone."""
    if str(environ.get(_FLAG, "")).strip() != "1":
        return False
    expected = {
        "RENDER": "true",
        "RENDER_SERVICE_ID": _SERVICE,
        "RENDER_SERVICE_TYPE": "web",
        "RENDER_EXTERNAL_HOSTNAME": _HOST,
        "RENDER_GIT_BRANCH": _BRANCH,
    }
    if any(str(environ.get(k, "")).strip() != v for k, v in expected.items()):
        raise RuntimeError("SWES_WND_TEST_RUNTIME_CONTEXT_HOLD")
    if not isinstance(admission, TrustedStagingCheckoutAdmission):
        raise TypeError("SWES_WND_ADMISSION_REQUIRED")
    if admission.render_database_id != _DATABASE:
        raise RuntimeError("SWES_WND_DATABASE_HOLD")
    source_sha = str(environ.get("RENDER_GIT_COMMIT", "")).strip().lower()
    if (
        len(source_sha) != 40
        or any(c not in "0123456789abcdef" for c in source_sha)
        or admission.deployed_source_sha != source_sha
    ):
        raise RuntimeError("SWES_WND_SOURCE_PIN_HOLD")
    # Admit only actual Boolean attestations; strings such as "false" and
    # integers such as 1 must not satisfy private operator proof requirements.
    if not all((
        admission.isolated_synthetic_tenant_proven is True,
        admission.authenticated_service_checkout_scope_proven is True,
        admission.sandbox_provider_only_proven is True,
    )):
        raise RuntimeError("SWES_WND_PROTECTED_PROOF_HOLD")
    if (
        not isinstance(admission.binding, VerifiedGatewayMerchantBinding)
        or admission.binding.verification_state != "verified"
        or admission.binding.tenant_id != _TEST_TENANT
        or admission.binding.merchant_public_id != _TEST_MERCHANT
        or not isinstance(admission.client, XafPayV2Client)
        or admission.client.base_url != _GATEWAY
    ):
        raise RuntimeError("SWES_WND_BINDING_HOLD")
    if getattr(app.state, "wnd_gateway_checkout_runtime", None) is not None:
        raise RuntimeError("SWES_WND_RUNTIME_ALREADY_BOUND")
    app.state.wnd_gateway_checkout_runtime = SimpleNamespace(
        binding=admission.binding, client=admission.client
    )
    return True
