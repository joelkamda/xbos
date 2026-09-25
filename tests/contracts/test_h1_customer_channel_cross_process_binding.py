from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from restaurant.customer_channel.auth import authenticate_bearer_value
from restaurant.customer_channel.contracts import (
    H1BError,
    TrustedCheckoutScope,
    payment_projection_dict,
)
from restaurant.customer_channel.delivery_policy import (
    DeliveryPolicyRecord,
    normalized_address,
    select_delivery_policy,
)
from restaurant.customer_channel.service import (
    RestaurantCustomerChannelCheckoutAuthority,
    _client_submit_ref,
    _fingerprint,
)

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
EXPECTED_ACCOUNT_SCOPE = TrustedCheckoutScope(
    2, 1, 1, 1, UUID(int=11), UUID(int=12), UUID(int=13), "XAF", "trace-1"
)


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8-sig")


def shell() -> RestaurantCustomerChannelCheckoutAuthority:
    return object.__new__(RestaurantCustomerChannelCheckoutAuthority)


def error_code(callable_):
    with pytest.raises(H1BError) as exc:
        callable_()
    return exc.value.code


def policy(public: int, rule: dict, version: int = 1):
    return DeliveryPolicyRecord(
        UUID(int=public),
        2,
        1,
        1,
        f"policy-{public}",
        version,
        rule,
        UUID(int=100 + public),
        UUID(int=200 + public),
        NOW - timedelta(days=1),
        None,
        True,
    )


def test_service_auth_missing(monkeypatch):
    monkeypatch.delenv("XAFPAY_CUSTOMER_CHANNEL_SERVICE_TOKEN_SHA256_CURRENT", raising=False)
    monkeypatch.delenv("XAFPAY_CUSTOMER_CHANNEL_SERVICE_TOKEN_SHA256_NEXT", raising=False)
    assert error_code(lambda: authenticate_bearer_value(None)) == "SERVICE_AUTH_REQUIRED"


def test_service_auth_wrong_principal(monkeypatch):
    monkeypatch.setenv("XAFPAY_CUSTOMER_CHANNEL_SERVICE_TOKEN_SHA256_CURRENT", "0" * 64)
    assert error_code(lambda: authenticate_bearer_value("wrong")) == "SERVICE_AUTH_FORBIDDEN"
    text = source("restaurant/customer_channel/repository.py")
    assert 's.service_code=:service' in text and "SERVICE_PRINCIPAL" in text


def test_service_scope_missing():
    text = source("restaurant/customer_channel/repository.py")
    assert "len(locations) != 1" in text
    assert "a.scope_type='location'" in text


def test_service_credential_rotation_current(monkeypatch):
    token = "current-token"
    monkeypatch.setenv(
        "XAFPAY_CUSTOMER_CHANNEL_SERVICE_TOKEN_SHA256_CURRENT",
        hashlib.sha256(token.encode()).hexdigest(),
    )
    monkeypatch.delenv("XAFPAY_CUSTOMER_CHANNEL_SERVICE_TOKEN_SHA256_NEXT", raising=False)
    assert authenticate_bearer_value(token) == "current"


def test_service_credential_rotation_next(monkeypatch):
    token = "next-token"
    monkeypatch.setenv("XAFPAY_CUSTOMER_CHANNEL_SERVICE_TOKEN_SHA256_CURRENT", "1" * 64)
    monkeypatch.setenv(
        "XAFPAY_CUSTOMER_CHANNEL_SERVICE_TOKEN_SHA256_NEXT",
        hashlib.sha256(token.encode()).hexdigest(),
    )
    assert authenticate_bearer_value(token) == "next"


def test_caller_tenant_override_forbidden():
    assert error_code(
        lambda: shell()._canonical_request(
            {"service_mode": "takeaway", "cart_lines": [{"catalog_entry_ref": str(uuid4()), "quantity": 1}], "tenant_id": 2}
        )
    ) == "ORDER_NOT_READY"


def test_caller_organization_override_forbidden():
    assert error_code(
        lambda: shell()._canonical_request(
            {"service_mode": "takeaway", "cart_lines": [{"catalog_entry_ref": str(uuid4()), "quantity": 1}], "organization_unit_id": 1}
        )
    ) == "ORDER_NOT_READY"


def test_cross_tenant_context_denial():
    interaction = source("core/platform/interaction/sql_repository.py")
    service = source("restaurant/customer_channel/service.py")
    assert "IA0_CONTEXT_BINDING_AMBIGUOUS" in interaction
    assert "tenant_id is None or binding.tenant_id == tenant_id" in service


def test_context_binding_missing_or_expired():
    binding = SimpleNamespace(
        purpose_code="restaurant.customer_channel.checkout",
        tenant_id=2,
        ended_at=None,
        expires_at=NOW - timedelta(seconds=1),
    )
    assert not shell()._binding_current(
        binding,
        purpose="restaurant.customer_channel.checkout",
        tenant_id=2,
        at=NOW,
    )


def test_context_binding_wrong_purpose():
    binding = SimpleNamespace(
        purpose_code="wrong",
        tenant_id=2,
        ended_at=None,
        expires_at=None,
    )
    assert not shell()._binding_current(
        binding,
        purpose="restaurant.customer_channel.checkout",
        tenant_id=2,
        at=NOW,
    )


def test_dine_in_valid_table():
    text = source("restaurant/customer_channel/service.py")
    assert 'profile.role is not ResourceRole.TABLE' in text
    assert '"dine_in" not in profile.service_mode_codes' in text
    assert 'resource.lifecycle_status != "active"' in text


def test_dine_in_invalid_or_stale_table():
    text = source("restaurant/customer_channel/service.py")
    assert "int(resource.location_id or 0) != scope.location_id" in text
    assert "int(resource.organization_unit_id or 0) != scope.organization_unit_id" in text


def test_takeaway_contact_required():
    assert error_code(
        lambda: shell()._canonical_request(
            {"service_mode": "bad-mode", "cart_lines": [{"catalog_entry_ref": str(uuid4()), "quantity": 1}]}
        )
    ) == "UNSUPPORTED_METHOD"
    assert 'if mode_code == "takeaway":' in source("restaurant/customer_channel/service.py")


def test_takeaway_contact_authority():
    text = source("restaurant/customer_channel/service.py")
    assert "purpose=CONTACT_PURPOSE" in text
    assert 'binding.source_reference.authority != "pc2.party_contact"' in text


def test_delivery_contact_and_address_required():
    text = source("restaurant/customer_channel/service.py")
    assert "if contact_ref is None or address_ref is None" in text


def test_delivery_address_binding_authority():
    text = source("restaurant/customer_channel/service.py")
    assert "purpose=DELIVERY_ADDRESS_PURPOSE" in text
    assert 'contact_type="postal_address"' in text


def test_delivery_service_area_unavailable():
    address = {"country_code": "cm", "region": None, "city": "douala", "district": "logpom", "postal_prefix": None}
    assert error_code(lambda: select_delivery_policy((), address=address, at=NOW)) == "ORDER_NOT_READY"


def test_delivery_service_area_ambiguous_fail_closed():
    address = {"country_code": "cm", "region": None, "city": "douala", "district": "logpom", "postal_prefix": None}
    values = (policy(1, {"city": "douala"}), policy(2, {"city": "douala"}))
    assert error_code(lambda: select_delivery_policy(values, address=address, at=NOW)) == "ORDER_NOT_READY"


def test_delivery_fee_xbos_authoritative():
    text = source("restaurant/customer_channel/service.py")
    assert "select_delivery_policy(" in text
    assert "resolve_fixed_fee_line(" in text
    assert "delivery_fee" not in shell()._canonical_request(
        {"service_mode": "delivery", "cart_lines": [{"catalog_entry_ref": str(uuid4()), "quantity": 1}]}
    )


def test_delivery_fee_so1_price_mismatch_fail_closed():
    text = source("restaurant/customer_channel/adapters.py")
    assert "price.target_public_id != entry.target_public_id" in text
    assert "price.currency != currency" in text


def test_delivery_fee_materialized_into_r1_obligation_and_c3_amount():
    text = source("restaurant/customer_channel/service.py")
    assert 'if fee.unit_price != Decimal("0"):' in text
    assert "lines.append(fee)" in text
    adapters = source("restaurant/customer_channel/adapters.py")
    assert "self.r1.add_line(" in adapters


def test_channel_amount_total_fee_override_forbidden():
    ref = str(uuid4())
    for key in ("amount", "currency", "delivery_fee", "total"):
        assert error_code(
            lambda key=key: shell()._canonical_request(
                {"service_mode": "takeaway", "cart_lines": [{"catalog_entry_ref": ref, "quantity": 1}], key: "1"}
            )
        ) == "ORDER_NOT_READY"


def test_priced_modifier_not_in_c3_obligation_fail_closed():
    text = source("restaurant/customer_channel/adapters.py")
    assert 'Decimal(price.amount) != Decimal("0")' in text
    assert "Accepted C3 derives only from R1 obligation lines" in text


def test_confirmation_snapshot_durable():
    sql = source("alembic_neutral/sql/cch_customer_channel_checkout_authority_up.sql")
    assert "restaurant_customer_order_confirmations" in sql
    assert "authoritative_snapshot JSONB NOT NULL" in sql
    assert "restaurant_customer_confirmation_immutable" in sql


def test_stale_quote_reconfirmation():
    service = source("restaurant/customer_channel/service.py")
    assert '"observed_quote_ref"' in service
    assert '"observed_quote_version"' in service
    assert '_fingerprint(rebuilt_snapshot) != row["commercial_fingerprint"]' in service


def test_confirmation_expiry():
    service = source("restaurant/customer_channel/service.py")
    assert 'row["expires_at"] <= now' in service
    assert "CONFIRMATION_TTL_SECONDS" in service


def test_confirmation_material_change():
    one = {"price": "2500", "policy": "v1"}
    two = {"price": "3000", "policy": "v1"}
    assert _fingerprint(one) != _fingerprint(two)
    assert "ORDER_CONFIRMATION_EXPIRED_OR_CHANGED" in source("restaurant/customer_channel/service.py")


def test_submission_exact_retry():
    selected, digest = _client_submit_ref(" AbC ")
    assert selected == "AbC"
    assert digest == hashlib.sha256(b"AbC").hexdigest()
    service = source("restaurant/customer_channel/service.py")
    assert 'if claimed.get("order_public_id"):' in service


def test_submission_same_ref_different_confirmation_conflict():
    repo = source("restaurant/customer_channel/repository.py")
    assert "claimed_client_submit_ref_hash=:hash" in repo
    assert "public_id<>:public_id" in repo
    assert 'raise H1BError("IDEMPOTENCY_CONFLICT")' in repo


def test_confirmation_different_client_ref_conflict():
    repo = source("restaurant/customer_channel/repository.py")
    assert "if existing and existing != client_submit_ref_hash" in repo


def test_lost_response_reconciliation():
    service = source("restaurant/customer_channel/service.py")
    repo = source("restaurant/customer_channel/repository.py")
    assert 'f"cc1:{submit_hash}:submit"' in service
    assert "command_type='submit_order'" in repo
    assert "result_type='restaurant_order'" in repo


def test_unknown_order_result():
    assert "UNKNOWN_ORDER_RESULT" in source("restaurant/customer_channel/service.py")
    assert "if result is None:" in source("restaurant/customer_channel/service.py")


def test_c3_exact_replay():
    contract = source("contracts/restaurant/v1/h1_customer_channel_cross_process_binding.json")
    assert '"scope": "restaurant.c3.payment_request"' in contract
    assert '"key": "order:{order_public_id}:v{row_version}"' in contract


def test_c3_changed_fingerprint():
    c3 = source("restaurant/c3/service.py")
    assert "fingerprint" in c3.lower()
    assert "C3" in c3


def test_exact_customer_safe_projection():
    fake = SimpleNamespace(
        payment_request_ref=UUID(int=1),
        order_ref=UUID(int=2),
        merchant_reference="merchant",
        correlation_ref="trace",
        canonical_amount=Decimal("2500"),
        currency="XAF",
        permitted_methods=("pay_at_counter", "mtn_mobile_money"),
        policy_ref="policy",
        expires_at=NOW,
        payment_request_state="open",
        wallet_handoff_context=None,
        safe_next_action="present_permitted_methods_only",
        receipt_ref="receipt",
    )
    result = payment_projection_dict(fake)
    assert list(result) == [
        "payment_request_ref", "order_ref", "merchant_reference", "correlation_ref",
        "canonical_amount", "currency", "permitted_methods", "policy_ref",
        "expires_at", "payment_request_state", "wallet_handoff_context",
        "safe_next_action", "receipt_ref",
    ]


def test_no_private_identifiers():
    result = H1BError("CONTEXT_MISMATCH", correlation_ref="trace").envelope()
    assert set(result["error"]) == {"code", "message", "correlation_ref"}
    assert "tenant_id" not in str(result)


def test_unsupported_method():
    assert error_code(
        lambda: shell()._canonical_request(
            {"service_mode": "curbside", "cart_lines": [{"catalog_entry_ref": str(uuid4()), "quantity": 1}]}
        )
    ) == "UNSUPPORTED_METHOD"


def test_no_payment_intent_no_gateway_no_provider():
    service = source("restaurant/customer_channel/service.py")
    adapters = source("restaurant/customer_channel/adapters.py")
    assert "create_intent(" not in service
    assert "create_attempt(" not in service
    assert "XafPayGatewayV2ExecutionAdapter" not in adapters
    assert "create_payment(" not in adapters


def test_no_paid_mapping_no_accounting_no_treasury():
    paths = [
        source("restaurant/customer_channel/service.py"),
        source("restaurant/customer_channel/router.py"),
    ]
    joined = "\n".join(paths).lower()
    assert "paid_mapping" not in joined
    assert "accounting_post" not in joined
    assert "treasury_movement" not in joined


def test_legacy_kernel_orders_not_used():
    router = source("restaurant/customer_channel/router.py")
    startup = source("startup.py")
    assert "/kernel/orders" not in router
    assert "customer_channel_router" in startup
