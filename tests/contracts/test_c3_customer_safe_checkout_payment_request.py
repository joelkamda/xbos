from __future__ import annotations

import inspect
from dataclasses import fields, replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest

from core.domain.finance.payment_intent_contract import PaymentCommandIdempotencyConflict
from core.domain.finance.payment_intent_repository import PaymentRequestRecord
from restaurant.c3 import C3Error, CustomerSafeCheckoutPaymentRequestService, TrustedCheckoutContext
from restaurant.c3.contracts import CustomerSafePaymentRequestProjection
from restaurant.c3.service import (
    commercial_fingerprint,
    finance_correlation_id,
    idempotency_key,
    payment_request_public_id,
)
from restaurant.r1.contracts import (
    ObligationHandoff,
    ObligationHandoffLine,
    OrderLine,
    OrderLineLifecycle,
    OrderStatus,
    RestaurantOrder,
    TargetType,
)

ROOT = Path(__file__).resolve().parents[2]
BASE = datetime(2026, 9, 22, 9, 0, tzinfo=timezone.utc)
TENANT = 2
BRANCH = 1
ORG = 77
ORDER_ID = UUID("c3000000-0000-0000-0000-000000000001")
LINE_ID = UUID("c3000000-0000-0000-0000-000000000002")
TARGET_ID = UUID("c3000000-0000-0000-0000-000000000003")
PRICE_ID = UUID("c3000000-0000-0000-0000-000000000004")
PARTY_ID = UUID("c3000000-0000-0000-0000-000000000005")


def _line(*, quantity="2", unit="1500", lifecycle=OrderLineLifecycle.ACTIVE, public_id=LINE_ID):
    return OrderLine(
        public_id=public_id,
        tenant_id=TENANT,
        order_public_id=ORDER_ID,
        target_type=TargetType.ATOMIC_UNIT,
        target_public_id=TARGET_ID,
        price_public_id=PRICE_ID,
        quantity=Decimal(quantity),
        unit_price_snapshot=Decimal(unit),
        currency="XAF",
        lifecycle_status=lifecycle,
    )


def _order(**changes):
    value = RestaurantOrder(
        public_id=ORDER_ID,
        tenant_id=TENANT,
        order_code="WND-C3-0001",
        mode_code="takeaway",
        source_channel_code="whatsapp",
        status=OrderStatus.SUBMITTED,
        opened_at=BASE,
        submitted_at=BASE,
        party_public_id=PARTY_ID,
        lines=(_line(),),
        row_version=7,
    )
    return replace(value, **changes)


def _handoff(order=None, *, amount=None, currency="XAF", source_type="restaurant_order", lines=None):
    order = order or _order()
    handoff_lines = lines
    if handoff_lines is None:
        handoff_lines = tuple(
            ObligationHandoffLine(
                x.public_id,
                x.target_type,
                x.target_public_id,
                x.quantity,
                x.unit_price_snapshot,
                x.currency,
                x.commercial_total,
            )
            for x in order.lines
            if x.lifecycle_status is OrderLineLifecycle.ACTIVE
        )
    total = amount if amount is not None else sum((x.commercial_amount for x in handoff_lines), Decimal("0"))
    return ObligationHandoff(
        tenant_id=TENANT,
        source_type=source_type,
        source_public_id=order.public_id,
        mode_code=order.mode_code,
        party_public_id=order.party_public_id,
        currency=currency,
        lines=handoff_lines,
        commercial_total=Decimal(total),
    )


class FakeRestaurant:
    def __init__(self, order=None, handoff=None):
        self.value = order or _order()
        self.handoff_value = handoff or _handoff(self.value)
        self.calls = []
        self.handoff_error = None

    def order(self, tenant_id, order_public_id):
        self.calls.append(("order", tenant_id, order_public_id))
        if tenant_id != self.value.tenant_id or order_public_id != self.value.public_id:
            raise C3Error("R1_ORDER_NOT_FOUND")
        return self.value

    def obligation_handoff(self, tenant_id, order_public_id):
        self.calls.append(("handoff", tenant_id, order_public_id))
        if self.handoff_error:
            raise self.handoff_error
        if tenant_id != self.value.tenant_id or order_public_id != self.value.public_id:
            raise C3Error("R1_ORDER_NOT_FOUND")
        return self.handoff_value


class FakeStructure:
    def __init__(self, organization_id=ORG):
        self.organization_id = organization_id
        self.calls = []
        self.fail = False

    def resolve(self, *, tenant_id, branch_id):
        self.calls.append((tenant_id, branch_id))
        if self.fail:
            raise C3Error("unmapped_legacy_branch")
        return SimpleNamespace(organization_unit=SimpleNamespace(id=self.organization_id))


class FakePolicy:
    def __init__(self, methods=None, version=3):
        self.methods = methods or ["cash", "mtn", "orange"]
        self.version = version
        self.calls = []

    def resolve(self, *, tenant_id, as_of):
        self.calls.append((tenant_id, as_of))
        return SimpleNamespace(value={"settlement_methods": list(self.methods)}, version=self.version)


class FakeFinance:
    def __init__(self):
        self.commands = []
        self.rows = {}

    def create(self, session, command):
        self.commands.append(command)
        identity = (command.tenant_id, command.idempotency_scope, command.idempotency_key)
        previous = self.rows.get(identity)
        if previous is not None:
            fingerprint, record = previous
            if fingerprint != command.request_fingerprint:
                raise PaymentCommandIdempotencyConflict(
                    "payment_command_idempotency_conflict",
                    "same identity has different command content",
                )
            return SimpleNamespace(payment_request=replace(record, replayed=True), replayed=True)
        record = PaymentRequestRecord(
            id=len(self.rows) + 1,
            public_id=command.public_id,
            tenant_id=command.tenant_id,
            organization_unit_id=command.organization_unit_id,
            request_state="open",
            purpose_code=command.purpose_code,
            requested_amount=command.requested_amount,
            currency_code=command.currency_code,
            expires_at=command.expires_at,
            row_version=1,
            committed_intent_amount=Decimal("0"),
        )
        self.rows[identity] = (command.request_fingerprint, record)
        return SimpleNamespace(payment_request=record, replayed=False)


def _service(*, order=None, handoff=None, methods=None, organization_id=ORG):
    restaurant = FakeRestaurant(order, handoff)
    structure = FakeStructure(organization_id)
    policy = FakePolicy(methods)
    finance = FakeFinance()
    service = CustomerSafeCheckoutPaymentRequestService(
        restaurant=restaurant,
        structure=structure,
        payment_policy=policy,
        finance=finance,
    )
    return service, restaurant, structure, policy, finance


def _call(service, *, tenant=TENANT, branch=BRANCH, actor=9):
    return service.create_payment_request(
        None,
        context=TrustedCheckoutContext(tenant, branch, actor),
        order_public_id=ORDER_ID,
    )


def test_01_submitted_order_required():
    service, *_ = _service(order=_order(status=OrderStatus.OPEN, submitted_at=None))
    with pytest.raises(C3Error, match="C3_ORDER_NOT_SUBMITTED"):
        _call(service)


def test_02_open_order_rejected():
    service, *_ = _service(order=_order(status=OrderStatus.OPEN, submitted_at=None))
    with pytest.raises(C3Error) as exc:
        _call(service)
    assert exc.value.code == "C3_ORDER_NOT_SUBMITTED"


def test_03_cancelled_order_rejected():
    service, *_ = _service(order=_order(status=OrderStatus.CANCELLED))
    with pytest.raises(C3Error) as exc:
        _call(service)
    assert exc.value.code == "C3_ORDER_NOT_SUBMITTED"


def test_04_empty_order_rejected():
    service, *_ = _service(order=_order(lines=()))
    with pytest.raises(C3Error) as exc:
        _call(service)
    assert exc.value.code == "C3_ORDER_EMPTY"


def test_05_removed_line_excluded():
    removed = _line(quantity="9", unit="9999", lifecycle=OrderLineLifecycle.REMOVED, public_id=UUID(int=88))
    order = _order(lines=(_line(), removed))
    handoff = _handoff(order, lines=(_handoff(_order()).lines[0],), amount="3000")
    service, *_ = _service(order=order, handoff=handoff)
    projection = _call(service)
    assert projection.canonical_amount == Decimal("3000.00000000")


def test_06_mixed_currency_rejected():
    service, restaurant, *_ = _service()
    restaurant.handoff_error = ValueError("R1_MIXED_CURRENCY_ORDER")
    with pytest.raises(ValueError, match="R1_MIXED_CURRENCY_ORDER"):
        _call(service)


def test_07_amount_derived_from_obligation_handoff():
    service, *_ = _service(handoff=_handoff(amount="4321"))
    projection = _call(service)
    assert projection.canonical_amount == Decimal("4321.00000000")


def test_08_currency_derived_from_obligation_handoff():
    service, *_ = _service(handoff=_handoff(currency="XAF"))
    projection = _call(service)
    assert projection.currency == "XAF"


def test_09_tenant_derived_from_trusted_context():
    service, restaurant, structure, *_ = _service()
    _call(service)
    assert restaurant.calls[0][1] == TENANT
    assert structure.calls == [(TENANT, BRANCH)]


def test_10_cross_tenant_order_lookup_forbidden():
    service, *_ = _service()
    with pytest.raises(C3Error, match="R1_ORDER_NOT_FOUND"):
        _call(service, tenant=TENANT + 1)


def test_11_organization_unit_derived_from_branch_mapping():
    service, _, structure, _, finance = _service(organization_id=1234)
    _call(service, branch=17)
    assert structure.calls == [(TENANT, 17)]
    assert finance.commands[0].organization_unit_id == 1234


def test_12_unmapped_branch_rejected():
    service, _, structure, *_ = _service()
    structure.fail = True
    with pytest.raises(C3Error, match="unmapped_legacy_branch"):
        _call(service)


def test_13_caller_tenant_override_forbidden():
    parameters = inspect.signature(CustomerSafeCheckoutPaymentRequestService.create_payment_request).parameters
    assert "tenant_id" not in parameters


def test_14_caller_organization_override_forbidden():
    parameters = inspect.signature(CustomerSafeCheckoutPaymentRequestService.create_payment_request).parameters
    assert "organization_unit_id" not in parameters


def test_15_idempotent_exact_replay_returns_one_request():
    service, _, _, _, finance = _service()
    first = _call(service)
    second = _call(service)
    assert first.payment_request_ref == second.payment_request_ref
    assert len(finance.rows) == 1
    assert finance.commands[0].idempotency_key == f"order:{ORDER_ID}:v7"
    assert finance.commands[1].idempotency_key == f"order:{ORDER_ID}:v7"


def test_16_changed_commercial_fingerprint_conflicts():
    service, restaurant, _, _, finance = _service()
    _call(service)
    restaurant.handoff_value = _handoff(amount="3001")
    with pytest.raises(PaymentCommandIdempotencyConflict):
        _call(service)
    assert len(finance.rows) == 1


def test_17_deterministic_public_id_stable():
    expected = uuid5(NAMESPACE_URL, f"xbos:restaurant:c3:payment-request:{TENANT}:{ORG}:{ORDER_ID}:v7")
    actual = payment_request_public_id(
        tenant_id=TENANT,
        organization_unit_id=ORG,
        order_public_id=ORDER_ID,
        row_version=7,
    )
    other = payment_request_public_id(
        tenant_id=TENANT,
        organization_unit_id=ORG,
        order_public_id=ORDER_ID,
        row_version=8,
    )
    assert actual == expected
    assert other != actual
    assert idempotency_key(ORDER_ID, 7).endswith(":v7")


def test_18_purpose_code_derived_from_restaurant_order_source_type():
    service, _, _, _, finance = _service()
    _call(service)
    assert finance.commands[0].purpose_code == "restaurant_order"


def test_19_payer_party_mapping_from_handoff():
    service, _, _, _, finance = _service()
    _call(service)
    assert finance.commands[0].payer_party_id == PARTY_ID


def test_20_occurred_at_derived_from_submitted_at():
    submitted = datetime(2026, 9, 22, 11, 12, tzinfo=timezone.utc)
    service, _, _, _, finance = _service(order=_order(submitted_at=submitted))
    _call(service)
    assert finance.commands[0].occurred_at == submitted


def test_21_business_date_derived_from_wnd_calendar():
    submitted = datetime(2026, 9, 22, 6, 30, tzinfo=timezone.utc)  # 07:30 Douala -> prior business date
    service, _, _, _, finance = _service(order=_order(submitted_at=submitted))
    _call(service)
    assert finance.commands[0].business_date.isoformat() == "2026-09-21"


def test_22_calendar_version_derived_from_wnd_calendar():
    service, _, _, _, finance = _service()
    _call(service)
    assert finance.commands[0].calendar_policy_version == 1


def test_23_payment_method_policy_resolved_from_pc4():
    service, _, _, policy, finance = _service()
    _call(service)
    assert policy.calls == [(TENANT, BASE)]
    assert finance.commands[0].metadata["payment_policy_ref"] == "wnd.payments.enabled_methods@3"


def test_24_payment_method_mapping_cash_mtn_orange():
    service, *_ = _service()
    projection = _call(service)
    assert projection.permitted_methods == ("pay_at_counter", "mtn_mobile_money", "orange_money")


def test_25_unknown_payment_method_fails_closed():
    service, *_ = _service(methods=["cash", "mystery_rail"])
    with pytest.raises(C3Error) as exc:
        _call(service)
    assert exc.value.code == "C3_PAYMENT_METHOD_UNSUPPORTED"


def test_26_customer_amount_override_forbidden():
    parameters = inspect.signature(CustomerSafeCheckoutPaymentRequestService.create_payment_request).parameters
    assert "amount" not in parameters and "requested_amount" not in parameters


def test_27_customer_currency_override_forbidden():
    parameters = inspect.signature(CustomerSafeCheckoutPaymentRequestService.create_payment_request).parameters
    assert "currency" not in parameters and "currency_code" not in parameters


def test_28_projection_exposes_no_private_identifiers():
    names = tuple(field.name for field in fields(CustomerSafePaymentRequestProjection))
    assert names == (
        "payment_request_ref", "order_ref", "merchant_reference", "correlation_ref",
        "canonical_amount", "currency", "permitted_methods", "policy_ref", "expires_at",
        "payment_request_state", "wallet_handoff_context", "safe_next_action", "receipt_ref",
    )
    assert not {"tenant_id", "organization_unit_id", "branch_id"}.intersection(names)


def test_29_payment_request_creation_does_not_imply_paid():
    service, *_ = _service()
    projection = _call(service)
    assert projection.payment_request_state == "open"
    assert projection.receipt_ref is None


def test_30_browser_redirect_does_not_imply_paid():
    source = (ROOT / "restaurant/c3/service.py").read_text(encoding="utf-8-sig").lower()
    assert "redirect" not in source
    assert _call(_service()[0]).payment_request_state == "open"


def test_31_channel_fake_success_does_not_imply_paid():
    source = (ROOT / "restaurant/c3/service.py").read_text(encoding="utf-8-sig").lower()
    assert "fake_success" not in source and "fake payment" not in source
    assert _call(_service()[0]).payment_request_state == "open"


def test_32_no_gateway_call():
    source = "\n".join((ROOT / f"restaurant/c3/{name}").read_text(encoding="utf-8-sig").lower() for name in ("service.py", "adapters.py"))
    assert "gateway" not in source


def test_33_no_provider_call():
    source = "\n".join((ROOT / f"restaurant/c3/{name}").read_text(encoding="utf-8-sig").lower() for name in ("service.py", "adapters.py"))
    assert "provider" not in source
    assert "requests." not in source and "httpx" not in source


def test_34_no_xafpay_core_service_call():
    source = "\n".join((ROOT / f"restaurant/c3/{name}").read_text(encoding="utf-8-sig").lower() for name in ("service.py", "adapters.py"))
    assert "xafpay_core" not in source and "core.integrations.xafpay" not in source


def test_35_no_second_financial_ledger():
    source = "\n".join((ROOT / f"restaurant/c3/{name}").read_text(encoding="utf-8-sig").lower() for name in ("service.py", "adapters.py"))
    assert "insert into" not in source and "sqlalchemy" not in source and "create_intent" not in source and "transactionalpaymentsettlementengine" not in source and "create_settlement" not in source


def test_36_xc8_semantic_compatibility():
    names = {field.name for field in fields(CustomerSafePaymentRequestProjection)}
    assert {"payment_request_ref", "order_ref", "correlation_ref", "canonical_amount", "currency", "permitted_methods", "policy_ref"} <= names
    service, *_ = _service()
    projection = _call(service)
    assert projection.safe_next_action == "present_permitted_methods_only"
    assert projection.wallet_handoff_context is None
    assert finance_correlation_id(tenant_id=TENANT, organization_unit_id=ORG, order_public_id=ORDER_ID, row_version=7) == UUID(projection.correlation_ref)
    assert commercial_fingerprint(_order(), _handoff(), "wnd.payments.enabled_methods@3")
