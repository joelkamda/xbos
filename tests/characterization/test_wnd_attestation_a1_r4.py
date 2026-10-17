from __future__ import annotations

from pathlib import Path

from core.integrations.xafpay_v2.attestation_service import (
    ATTESTATION_PERMISSION,
    ATTESTATION_PURPOSE,
    GATEWAY_PATH,
    WND_ATTESTATION_TARGET,
)
from core.rbac.permissions.permission_groups import PERMISSION_GROUPS
from core.rbac.permissions.permission_registry import PERMISSION_REGISTRY


ROOT = Path(__file__).resolve().parents[2]
ROUTER = ROOT / "core/api/payments/wnd_attestation_router.py"
SERVICE = ROOT / "core/integrations/xafpay_v2/attestation_service.py"
CLIENT = ROOT / "core/integrations/xafpay_v2/attestation_client.py"
KERNEL = ROOT / "core/api/kernel_router.py"
SEED = ROOT / "core/rbac/seeds/seed_permissions.py"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_exact_operator_route_is_registered_once_without_alias():
    router = _text(ROUTER)
    kernel = _text(KERNEL)

    assert router.count('@router.post("/xafpay/attestation/execute")') == 1
    assert "wnd_attestation_router" in kernel
    assert 'prefix="/payments"' in kernel
    assert (
        PERMISSION_REGISTRY.resolve(
            "/kernel/payments/xafpay/attestation/execute",
            "POST",
        )
        == ATTESTATION_PERMISSION
    )
    assert (
        PERMISSION_REGISTRY.resolve(
            "/kernel/payments/xafpay/attestation/execute",
            "GET",
        )
        is None
    )


def test_attestation_permission_is_not_implicitly_grouped_or_seed_granted():
    for permissions in PERMISSION_GROUPS.values():
        assert ATTESTATION_PERMISSION not in permissions

    # R4-W registers a valid permission code but intentionally does not
    # auto-grant it through the legacy permission seed.
    assert ATTESTATION_PERMISSION not in _text(SEED)


def test_router_requires_explicit_authenticated_operator_context():
    source = _text(ROUTER)
    assert 'request.headers.get("Authorization"' in source
    assert "JWTService().decode_token(token)" in source
    assert "tenant_id != int(user.get" in source
    assert "branch_id != int(user.get" in source
    assert "ATTESTATION_PERMISSION not in permission_set" in source
    assert '"*"' not in source
    assert "payments.receive" not in source.lower()


def test_runtime_dependency_is_default_deny():
    source = _text(ROUTER)
    assert "_DISABLED_SERVICE = WndAttestationService.disabled()" in source
    assert "return _DISABLED_SERVICE" in source
    assert "os.getenv" not in source
    assert "get_db" not in source
    assert "DATABASE_URL" not in source


def test_source_contains_no_live_network_implementation():
    client = _text(CLIENT)
    service = _text(SERVICE)
    combined = client + "\n" + service

    forbidden = (
        "import httpx",
        "from httpx",
        "import requests",
        "from requests",
        "urllib.request",
        "socket.create_connection",
        "aiohttp",
    )
    for needle in forbidden:
        assert needle not in combined

    assert "class AttestationTransport(Protocol)" in client
    assert "follow_redirects=False" in client
    assert "ATTESTATION_TRANSPORT_TIMEOUT" in client
    assert "ATTESTATION_REDIRECT_REJECTED" in client


def test_source_has_no_payment_checkout_provider_or_database_execution():
    combined = _text(ROUTER) + "\n" + _text(SERVICE) + "\n" + _text(CLIENT)
    forbidden = (
        "WndXafPayV2Service",
        "PaymentsController",
        "payments_controller",
        ".create_checkout(",
        "TransactionalPaymentIntentEngine",
        "TransactionalPaymentTenderEngine",
        "TransactionalPaymentAttemptEngine",
        "MTN_MOMO",
        "ORANGE_MONEY",
        "tranzak",
        "psycopg",
        "sqlalchemy",
        "get_db",
        "DATABASE_URL",
    )
    for needle in forbidden:
        assert needle not in combined


def test_source_never_generates_or_loads_real_keys():
    service = _text(SERVICE)
    forbidden = (
        "generate_private_key",
        "private_bytes(",
        "load_pem_private_key",
        "load_der_private_key",
        "open(",
        "Path(",
        "os.environ",
        "os.getenv",
    )
    for needle in forbidden:
        assert needle not in service


def test_no_secret_or_body_logging_surface():
    combined = _text(SERVICE) + "\n" + _text(CLIENT)
    assert "print(" not in combined
    assert "logging." not in combined
    assert ".debug(" not in combined
    assert ".info(" not in combined
    assert ".warning(" not in combined


def test_exact_gateway_contract_constants_are_frozen():
    assert ATTESTATION_PURPOSE == "wnd.credential-binding.attest.v1"
    assert GATEWAY_PATH == "/internal/wnd-credential-attestations/v1/redeem"
    assert WND_ATTESTATION_TARGET == {
        "credential_id": "8af0fbaf-024b-4ab8-9f99-117a74e952c7",
        "merchant_id": "mch_01a0a40c-d9fa-7962-95b6-706633e3bd1c",
        "subject": "xbos",
        "audience": "xafpay-gateway-v2",
        "environment": "STAGING",
        "required_scope": "checkout:create",
    }
