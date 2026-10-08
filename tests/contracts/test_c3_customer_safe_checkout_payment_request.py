from __future__ import annotations

import inspect
from dataclasses import fields, replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest

from core.domain.finance.payment_intent_contract import (
    PaymentCommandIdempotencyConflict,
    PaymentCommandValidationError,
)
from core.domain.finance.payment_intent_repository import PaymentRequestRecord
from core.integrations.xafpay.contract import XafPayPaymentCreateRequest, XafPayPaymentCreateResponse
from restaurant.c3 import C3Error, CustomerSafeCheckoutPaymentRequestService, TrustedCheckoutContext
from restaurant.c3.contracts import CustomerSafePaymentRequestProjection
from restaurant.c3.service import (
    ExternalMethodPaymentExecutionService,
    c4_idempotency_key,
    commercial_fingerprint,
    finance_correlation_id,
    idempotency_key,
    payment_attempt_public_id,
    payment_intent_public_id,
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


def test_07a_trailing_zero_scale_12_amount_normalizes_exactly_at_finance_boundary():
    service, _, _, _, finance = _service(handoff=_handoff(amount="2500.000000000000"))
    projection = _call(service)
    assert finance.commands[0].requested_amount == Decimal("2500.00000000")
    assert projection.canonical_amount == Decimal("2500.00000000")


def test_07b_trailing_zero_normalization_preserves_commercial_fingerprint():
    order = _order()
    handoff = _handoff(order, amount="2500.000000000000")
    expected = commercial_fingerprint(order, handoff, "wnd.payments.enabled_methods@3")
    service, _, _, _, finance = _service(order=order, handoff=handoff)
    _call(service)
    assert finance.commands[0].metadata["commercial_fingerprint"] == expected


def test_07c_nine_meaningful_decimal_places_remain_rejected():
    service, *_ = _service(handoff=_handoff(amount="1.123456789"))
    with pytest.raises(PaymentCommandValidationError) as exc:
        _call(service)
    assert exc.value.code == "invalid_money"
    assert "at most eight decimals" in str(exc.value)


def test_07d_standard_existing_amount_path_remains_unchanged():
    service, _, _, _, finance = _service(handoff=_handoff(amount="4321"))
    projection = _call(service)
    assert finance.commands[0].requested_amount == Decimal("4321.00000000")
    assert projection.canonical_amount == Decimal("4321.00000000")


def test_07e_deterministic_identities_unchanged_for_scale_12_amount():
    service, _, _, _, finance = _service(handoff=_handoff(amount="2500.000000000000"))
    projection = _call(service)
    assert projection.payment_request_ref == str(
        payment_request_public_id(
            tenant_id=TENANT, organization_unit_id=ORG, order_public_id=ORDER_ID, row_version=7
        )
    )
    assert projection.correlation_ref == str(
        finance_correlation_id(
            tenant_id=TENANT, organization_unit_id=ORG, order_public_id=ORDER_ID, row_version=7
        )
    )
    assert finance.commands[0].idempotency_key == f"order:{ORDER_ID}:v7"


def test_07f_scale_12_exact_replay_still_returns_one_request():
    service, _, _, _, finance = _service(handoff=_handoff(amount="2500.000000000000"))
    first = _call(service)
    second = _call(service)
    assert first == second
    assert len(finance.rows) == 1
    assert len(finance.commands) == 2
    assert finance.commands[0].request_fingerprint == finance.commands[1].request_fingerprint


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


def _c3_request_service_source():
    source = (ROOT / "restaurant/c3/service.py").read_text(encoding="utf-8-sig").lower()
    return source.split("class customersafecheckoutpaymentrequestservice", 1)[1].split(
        "class externalmethodpaymentexecutionservice", 1
    )[0]


def test_32_no_gateway_call():
    source = _c3_request_service_source()
    assert "gateway" not in source


def test_33_no_provider_call():
    source = _c3_request_service_source()
    assert "provider" not in source
    assert "requests." not in source and "httpx" not in source


def test_34_no_xafpay_core_service_call():
    source = _c3_request_service_source()
    assert "xafpay_core" not in source and "core.integrations.xafpay" not in source


def test_35_no_second_financial_ledger():
    source = _c3_request_service_source()
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


class FakeC4Finance(FakeFinance):
    def __init__(self):
        super().__init__()
        self.intent_rows = {}
        self.attempt_rows = {}

    def find_request(self, session, *, tenant_id, public_id):
        for _, record in self.rows.values():
            if record.tenant_id == tenant_id and record.public_id == public_id:
                return record
        return None

    def create_intent(self, session, command):
        identity = (command.tenant_id, command.idempotency_scope, command.idempotency_key)
        previous = self.intent_rows.get(identity)
        if previous is not None:
            fingerprint, record = previous
            if fingerprint != command.request_fingerprint:
                raise PaymentCommandIdempotencyConflict(
                    "payment_command_idempotency_conflict",
                    "same identity has different intent content",
                )
            return SimpleNamespace(payment_intent=record, replayed=True)
        record = SimpleNamespace(
            public_id=command.public_id,
            requested_amount=command.requested_amount,
            currency_code=command.currency_code,
            payment_method_policy=command.payment_method_policy,
            intent_state="pending",
            row_version=1,
            replayed=False,
        )
        self.intent_rows[identity] = (command.request_fingerprint, record)
        return SimpleNamespace(payment_intent=record, replayed=False)

    def create_attempt(self, session, command):
        identity = (command.tenant_id, command.idempotency_scope, command.idempotency_key)
        previous = self.attempt_rows.get(identity)
        if previous is not None:
            fingerprint, record = previous
            if fingerprint != command.request_fingerprint:
                raise PaymentCommandIdempotencyConflict(
                    "payment_command_idempotency_conflict",
                    "same identity has different attempt content",
                )
            return SimpleNamespace(payment_attempt=record, replayed=True)
        record = SimpleNamespace(
            public_id=command.public_id,
            payment_intent_public_id=command.payment_intent_public_id,
            payment_method_code=command.payment_method_code,
            payment_rail_code=command.payment_rail_code,
            orchestrator_code=command.orchestrator_code,
            provider_account_id=None,
            underlying_provider_code=None,
            external_attempt_reference=None,
            attempt_state="pending",
            attempted_amount=command.attempted_amount,
            currency_code=command.currency_code,
            row_version=1,
            replayed=False,
        )
        self.attempt_rows[identity] = (command.request_fingerprint, record)
        return SimpleNamespace(payment_attempt=record, replayed=False)

    def attempt_by_public_id(self, public_id):
        for _, record in self.attempt_rows.values():
            if record.public_id == public_id:
                return record
        raise AssertionError("attempt not found")


class FakeC4Gateway:
    def __init__(self, finance, *, status="CREATED"):
        self.finance = finance
        self.status = status
        self.created = []
        self.recorded = []

    def prepare(self, session, **kwargs):
        attempt = self.finance.attempt_by_public_id(kwargs["payment_attempt_public_id"])
        return XafPayPaymentCreateRequest(
            payment_attempt_public_id=attempt.public_id,
            amount=attempt.attempted_amount,
            currency_code=attempt.currency_code,
            payment_method_code=attempt.payment_method_code,
            payment_rail_code=attempt.payment_rail_code,
            channel=kwargs["channel"],
        )

    def create(self, request, *, service_credential, transport):
        self.created.append((request, service_credential, transport))
        suffix = str(request.payment_attempt_public_id).replace("-", "")
        return XafPayPaymentCreateResponse(
            payment_id=f"pay_{suffix}",
            external_reference=request.external_reference,
            status=self.status,
            amount=request.amount,
            currency_code=request.currency_code,
            next_action=(
                {"type": "MOBILE_APPROVAL", "url": None}
                if self.status == "REQUIRES_ACTION"
                else None
            ),
            evidence={"fixture": "c4"},
        )

    def record(self, session, command):
        self.recorded.append(command)
        attempt = self.finance.attempt_by_public_id(command.payment_attempt_public_id)
        attempt.external_attempt_reference = command.response.payment_id
        attempt.attempt_state = (
            "requires_action" if command.response.status == "REQUIRES_ACTION" else "processing"
        )
        attempt.row_version += 1
        return attempt


def _c4_service(*, methods=None, gateway_status="CREATED"):
    restaurant = FakeRestaurant()
    structure = FakeStructure()
    policy = FakePolicy(methods)
    finance = FakeC4Finance()
    checkout = CustomerSafeCheckoutPaymentRequestService(
        restaurant=restaurant,
        structure=structure,
        payment_policy=policy,
        finance=finance,
    )
    c3_projection = checkout.create_payment_request(
        None,
        context=TrustedCheckoutContext(TENANT, BRANCH, 9),
        order_public_id=ORDER_ID,
    )
    gateway = FakeC4Gateway(finance, status=gateway_status)
    execution = ExternalMethodPaymentExecutionService(
        restaurant=restaurant,
        structure=structure,
        payment_policy=policy,
        finance=finance,
        gateway=gateway,
    )
    execution._test_payment_request_public_id = UUID(c3_projection.payment_request_ref)
    return execution, finance, gateway


def _c4_call(service, selected_method):
    return service.execute(
        None,
        context=TrustedCheckoutContext(TENANT, BRANCH, 9),
        order_public_id=ORDER_ID,
        payment_request_ref=service._test_payment_request_public_id,
        selected_method=selected_method,
        service_credential="gateway-service-credential",
        transport=object(),
        channel="customer-channel",
    )


def test_c4_mtn_selection_creates_one_canonical_intent():
    service, finance, _ = _c4_service()
    result = _c4_call(service, "mtn_mobile_money")
    assert len(finance.intent_rows) == 1
    assert result.payment_intent_ref == str(payment_intent_public_id(UUID(result.payment_request_ref)))


def test_c4_mtn_selection_creates_one_canonical_attempt():
    service, finance, _ = _c4_service()
    result = _c4_call(service, "mtn_mobile_money")
    assert len(finance.attempt_rows) == 1
    assert result.payment_attempt_ref == str(payment_attempt_public_id(UUID(result.payment_request_ref)))


def test_c4_orange_selection_creates_one_canonical_intent():
    service, finance, _ = _c4_service()
    _c4_call(service, "orange_money")
    assert len(finance.intent_rows) == 1


def test_c4_orange_selection_creates_one_canonical_attempt():
    service, finance, _ = _c4_service()
    result = _c4_call(service, "orange_money")
    assert len(finance.attempt_rows) == 1
    assert result.payment_rail_code == "orange_money"


@pytest.mark.parametrize(
    "selected,expected",
    [
        ("mtn_mobile_money", ("mobile_money", "mtn_momo")),
        ("orange_money", ("mobile_money", "orange_money")),
    ],
)
def test_c4_method_rail_mapping_exact(selected, expected):
    service, _, _ = _c4_service()
    result = _c4_call(service, selected)
    assert (result.payment_method_code, result.payment_rail_code) == expected


def test_c4_exact_replay_reuses_intent_and_attempt():
    service, finance, gateway = _c4_service()
    first = _c4_call(service, "mtn_mobile_money")
    second = _c4_call(service, "mtn_mobile_money")
    assert first.payment_intent_ref == second.payment_intent_ref
    assert first.payment_attempt_ref == second.payment_attempt_ref
    assert len(finance.intent_rows) == 1
    assert len(finance.attempt_rows) == 1
    assert len(gateway.created) == 2


def test_c4_gateway_external_reference_binds_attempt():
    service, _, gateway = _c4_service()
    result = _c4_call(service, "mtn_mobile_money")
    request = gateway.created[0][0]
    expected = f"xbos:pay:{result.payment_attempt_ref}"
    assert request.external_reference == expected
    assert result.gateway_external_reference == expected


def test_c4_gateway_idempotency_is_replay_stable():
    service, _, gateway = _c4_service()
    first = _c4_call(service, "orange_money")
    second = _c4_call(service, "orange_money")
    expected = f"xbos:pay:{first.payment_attempt_ref}"
    assert first.gateway_idempotency_key == expected
    assert second.gateway_idempotency_key == expected
    assert [item[0].idempotency_key for item in gateway.created] == [expected, expected]


def test_c4_non_external_or_non_permitted_method_fails_closed():
    service, finance, gateway = _c4_service()
    with pytest.raises(C3Error) as caught:
        _c4_call(service, "pay_at_counter")
    assert caught.value.code == "C4_EXTERNAL_METHOD_REQUIRED"
    assert not finance.intent_rows
    assert not finance.attempt_rows
    assert not gateway.created


def test_c4_method_switch_after_first_attempt_conflicts_instead_of_second_attempt():
    service, finance, gateway = _c4_service()
    _c4_call(service, "mtn_mobile_money")
    with pytest.raises(PaymentCommandIdempotencyConflict):
        _c4_call(service, "orange_money")
    assert len(finance.intent_rows) == 1
    assert len(finance.attempt_rows) == 1
    assert len(gateway.created) == 1


def test_c4_gateway_owned_provider_routing_remains_unbound_in_xbos_attempt():
    service, finance, _ = _c4_service()
    result = _c4_call(service, "orange_money")
    attempt = finance.attempt_by_public_id(UUID(result.payment_attempt_ref))
    assert attempt.provider_account_id is None
    assert attempt.underlying_provider_code is None
    assert attempt.orchestrator_code == "xafpay"


def test_c4_gateway_create_records_nonterminal_gateway_identity_only():
    service, finance, _ = _c4_service(gateway_status="REQUIRES_ACTION")
    result = _c4_call(service, "mtn_mobile_money")
    attempt = finance.attempt_by_public_id(UUID(result.payment_attempt_ref))
    assert result.gateway_payment_id.startswith("pay_")
    assert attempt.external_attempt_reference == result.gateway_payment_id
    assert result.attempt_state == "requires_action"


def test_c4_no_settlement_paid_accounting_or_treasury_path():
    source = (ROOT / "restaurant/c3/service.py").read_text(encoding="utf-8-sig")
    c4 = source.split("class ExternalMethodPaymentExecutionService", 1)[1].lower()
    assert "payment_settlement" not in c4
    assert "create_settlement" not in c4
    assert "paid" not in c4
    assert "accounting" not in c4
    assert "treasury" not in c4
    assert "provider_account_public_id=none" in c4
    assert c4_idempotency_key(UUID(int=1)) == "request:00000000-0000-0000-0000-000000000001"
