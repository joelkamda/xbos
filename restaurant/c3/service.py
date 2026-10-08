from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

from core.domain.finance.payment_attempt_contract import CreatePaymentAttemptCommand
from core.domain.finance.payment_intent_contract import CreatePaymentIntentCommand, CreatePaymentRequestCommand
from core.integrations.xafpay.contract import RecordXafPayPaymentCreateCommand
from core.platform.operating_context import BusinessTimeResolver
from restaurant.r1.contracts import OrderStatus
from restaurant.r5 import build_wnd_calendar

from .contracts import (
    ACTOR_SERVICE,
    C4_ACTOR_SERVICE,
    C4_ATTEMPT_IDEMPOTENCY_SCOPE,
    C4_INTENT_IDEMPOTENCY_SCOPE,
    C4_SOURCE_COMPONENT,
    IDEMPOTENCY_SCOPE,
    PAYMENT_POLICY_KEY,
    PAYMENT_REQUEST_PURPOSE,
    SAFE_NEXT_ACTION,
    SOURCE_COMPONENT,
    C3Error,
    CustomerSafePaymentRequestProjection,
    ExternalPaymentExecutionHandoffProjection,
    TrustedCheckoutContext,
)


_METHOD_MAP = {
    "cash": "pay_at_counter",
    "mtn": "mtn_mobile_money",
    "orange": "orange_money",
}

_EXTERNAL_EXECUTION_METHODS = {
    "mtn_mobile_money": ("mobile_money", "mtn_momo"),
    "orange_money": ("mobile_money", "orange_money"),
}


def payment_intent_public_id(payment_request_public_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"xbos:restaurant:c4:intent:{payment_request_public_id}")


def payment_attempt_public_id(payment_request_public_id: UUID) -> UUID:
    return uuid5(NAMESPACE_URL, f"xbos:restaurant:c4:attempt:{payment_request_public_id}")


def c4_idempotency_key(payment_request_public_id: UUID) -> str:
    return f"request:{payment_request_public_id}"


def _decimal_text(value: Decimal) -> str:
    selected = Decimal(value)
    text = format(selected, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def _target_type_text(value) -> str:
    return str(getattr(value, "value", value))


def payment_request_public_id(*, tenant_id: int, organization_unit_id: int, order_public_id: UUID, row_version: int) -> UUID:
    seed = (
        "xbos:restaurant:c3:payment-request:"
        f"{tenant_id}:{organization_unit_id}:{order_public_id}:v{row_version}"
    )
    return uuid5(NAMESPACE_URL, seed)


def finance_correlation_id(*, tenant_id: int, organization_unit_id: int, order_public_id: UUID, row_version: int) -> UUID:
    seed = (
        "xbos:restaurant:c3:correlation:"
        f"{tenant_id}:{organization_unit_id}:{order_public_id}:v{row_version}"
    )
    return uuid5(NAMESPACE_URL, seed)


def source_record_reference(order_public_id: UUID, row_version: int) -> str:
    return f"restaurant_order:{order_public_id}:v{row_version}"


def idempotency_key(order_public_id: UUID, row_version: int) -> str:
    return f"order:{order_public_id}:v{row_version}"


def commercial_fingerprint(order, handoff, payment_policy_ref: str) -> str:
    lines = []
    for line in sorted(handoff.lines, key=lambda item: str(item.order_line_public_id)):
        lines.append(
            {
                "order_line_public_id": str(line.order_line_public_id),
                "target_type": _target_type_text(line.target_type),
                "target_public_id": str(line.target_public_id),
                "quantity": _decimal_text(line.quantity),
                "unit_price_snapshot": _decimal_text(line.unit_price_snapshot),
                "currency": str(line.currency).upper(),
                "commercial_amount": _decimal_text(line.commercial_amount),
            }
        )
    payload = {
        "order_public_id": str(order.public_id),
        "row_version": int(order.row_version),
        "mode_code": handoff.mode_code,
        "party_public_id": str(handoff.party_public_id) if handoff.party_public_id else None,
        "currency": str(handoff.currency).upper(),
        "active_handoff_lines": lines,
        "commercial_total": _decimal_text(handoff.commercial_total),
        "payment_policy_ref": payment_policy_ref,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _permitted_methods(configuration) -> tuple[str, ...]:
    value = getattr(configuration, "value", None)
    if not isinstance(value, dict):
        raise C3Error("C3_PAYMENT_POLICY_INVALID", "policy value must be a JSON object")
    raw = value.get("settlement_methods")
    if not isinstance(raw, list) or not raw:
        raise C3Error("C3_PAYMENT_POLICY_INVALID", "settlement_methods must be a non-empty list")
    mapped: list[str] = []
    for item in raw:
        code = str(item).strip().lower()
        if code not in _METHOD_MAP:
            raise C3Error("C3_PAYMENT_METHOD_UNSUPPORTED", code)
        customer_code = _METHOD_MAP[code]
        if customer_code not in mapped:
            mapped.append(customer_code)
    return tuple(mapped)


class CustomerSafeCheckoutPaymentRequestService:
    """Transport-neutral composition from accepted Restaurant truth to one Neutral Finance request."""

    def __init__(self, *, restaurant, structure, payment_policy, finance):
        self.restaurant = restaurant
        self.structure = structure
        self.payment_policy = payment_policy
        self.finance = finance

    def create_payment_request(self, session, *, context: TrustedCheckoutContext, order_public_id: UUID):
        order = self.restaurant.order(context.tenant_id, UUID(str(order_public_id)))
        if getattr(order, "tenant_id", None) != context.tenant_id:
            raise C3Error("C3_ORDER_SCOPE_MISMATCH", "order is outside trusted tenant")
        if order.status is not OrderStatus.SUBMITTED:
            raise C3Error("C3_ORDER_NOT_SUBMITTED", str(order.status))
        if order.submitted_at is None:
            raise C3Error("C3_ORDER_SUBMITTED_AT_REQUIRED")
        if not order.lines:
            raise C3Error("C3_ORDER_EMPTY")

        handoff = self.restaurant.obligation_handoff(context.tenant_id, order.public_id)
        if (
            handoff.tenant_id != context.tenant_id
            or handoff.source_type != PAYMENT_REQUEST_PURPOSE
            or handoff.source_public_id != order.public_id
            or handoff.finance_authority != "Neutral Finance"
            or handoff.creates_financial_truth
            or not handoff.lines
        ):
            raise C3Error("C3_HANDOFF_AUTHORITY_MISMATCH")

        structural = self.structure.resolve(tenant_id=context.tenant_id, branch_id=context.branch_id)
        organization = getattr(structural, "organization_unit", None)
        if organization is None:
            raise C3Error("C3_ORGANIZATION_UNIT_REQUIRED")
        organization_unit_id = int(organization.id)

        policy = self.payment_policy.resolve(tenant_id=context.tenant_id, as_of=order.submitted_at)
        if policy is None:
            raise C3Error("C3_PAYMENT_POLICY_REQUIRED")
        policy_version = int(getattr(policy, "version", 0))
        if policy_version < 0:
            raise C3Error("C3_PAYMENT_POLICY_INVALID", "configuration version cannot be negative")
        payment_policy_ref = f"{PAYMENT_POLICY_KEY}@{policy_version}"
        permitted_methods = _permitted_methods(policy)

        business_time = BusinessTimeResolver.resolve(build_wnd_calendar(context.tenant_id), order.submitted_at)
        fingerprint = commercial_fingerprint(order, handoff, payment_policy_ref)
        public_id = payment_request_public_id(
            tenant_id=context.tenant_id,
            organization_unit_id=organization_unit_id,
            order_public_id=order.public_id,
            row_version=order.row_version,
        )
        correlation_id = finance_correlation_id(
            tenant_id=context.tenant_id,
            organization_unit_id=organization_unit_id,
            order_public_id=order.public_id,
            row_version=order.row_version,
        )
        source_record_id = source_record_reference(order.public_id, order.row_version)
        command = CreatePaymentRequestCommand(
            public_id=public_id,
            tenant_id=context.tenant_id,
            organization_unit_id=organization_unit_id,
            purpose_code=PAYMENT_REQUEST_PURPOSE,
            requested_amount=Decimal(_decimal_text(handoff.commercial_total)),
            currency_code=handoff.currency,
            occurred_at=order.submitted_at,
            business_date=business_time.business_date,
            calendar_policy_version=business_time.calendar_version,
            correlation_id=correlation_id,
            source_component=SOURCE_COMPONENT,
            source_record_id=source_record_id,
            idempotency_scope=IDEMPOTENCY_SCOPE,
            idempotency_key=idempotency_key(order.public_id, order.row_version),
            payer_party_id=handoff.party_public_id,
            expires_at=None,
            actor_user_id=context.actor_user_id,
            actor_service=ACTOR_SERVICE,
            metadata={
                "commercial_fingerprint": fingerprint,
                "payment_policy_ref": payment_policy_ref,
                "permitted_methods": list(permitted_methods),
                "order_public_id": str(order.public_id),
                "order_row_version": int(order.row_version),
            },
        )
        result = self.finance.create(session, command)
        record = result.payment_request
        if (
            record.public_id != public_id
            or record.tenant_id != context.tenant_id
            or record.organization_unit_id != organization_unit_id
            or record.requested_amount != command.requested_amount
            or record.currency_code != command.currency_code
        ):
            raise C3Error("C3_FINANCE_RESULT_MISMATCH")
        if record.request_state != "open":
            raise C3Error("C3_CUSTOMER_SAFE_STATE_UNSUPPORTED", record.request_state)
        if record.expires_at is not None:
            raise C3Error("C3_CUSTOMER_SAFE_EXPIRY_UNSUPPORTED")

        return CustomerSafePaymentRequestProjection(
            payment_request_ref=str(record.public_id),
            order_ref=str(order.public_id),
            merchant_reference=order.order_code,
            correlation_ref=str(correlation_id),
            canonical_amount=record.requested_amount,
            currency=record.currency_code,
            permitted_methods=permitted_methods,
            policy_ref=payment_policy_ref,
            expires_at=None,
            payment_request_state="open",
            wallet_handoff_context=None,
            safe_next_action=SAFE_NEXT_ACTION,
            receipt_ref=None,
        )


def _record_value(record, name: str):
    if isinstance(record, dict):
        return record[name]
    try:
        return record[name]
    except (TypeError, KeyError):
        return getattr(record, name)


class ExternalMethodPaymentExecutionService:
    """C4: canonical intent/attempt creation followed by Gateway V2 payment creation only."""

    def __init__(self, *, restaurant, structure, payment_policy, finance, gateway):
        self.restaurant = restaurant
        self.structure = structure
        self.payment_policy = payment_policy
        self.finance = finance
        self.gateway = gateway

    def execute(
        self,
        session,
        *,
        context: TrustedCheckoutContext,
        order_public_id: UUID,
        payment_request_ref: UUID,
        selected_method: str,
        service_credential: str,
        transport,
        channel: str = "customer-channel",
    ) -> ExternalPaymentExecutionHandoffProjection:
        order = self.restaurant.order(context.tenant_id, UUID(str(order_public_id)))
        if order.status is not OrderStatus.SUBMITTED or order.submitted_at is None:
            raise C3Error("C4_ORDER_NOT_SUBMITTED")
        structural = self.structure.resolve(tenant_id=context.tenant_id, branch_id=context.branch_id)
        organization = getattr(structural, "organization_unit", None)
        if organization is None:
            raise C3Error("C4_ORGANIZATION_UNIT_REQUIRED")
        organization_unit_id = int(organization.id)

        request_public_id = UUID(str(payment_request_ref))
        expected_request_id = payment_request_public_id(
            tenant_id=context.tenant_id,
            organization_unit_id=organization_unit_id,
            order_public_id=order.public_id,
            row_version=order.row_version,
        )
        if request_public_id != expected_request_id:
            raise C3Error("C4_PAYMENT_REQUEST_ORDER_MISMATCH")
        request = self.finance.find_request(
            session,
            tenant_id=context.tenant_id,
            public_id=request_public_id,
        )
        if request is None:
            raise C3Error("C4_PAYMENT_REQUEST_NOT_FOUND")
        if request.organization_unit_id != organization_unit_id:
            raise C3Error("C4_PAYMENT_REQUEST_SCOPE_MISMATCH")
        if request.request_state != "open":
            raise C3Error("C4_PAYMENT_REQUEST_NOT_OPEN", request.request_state)

        policy = self.payment_policy.resolve(tenant_id=context.tenant_id, as_of=order.submitted_at)
        if policy is None:
            raise C3Error("C4_PAYMENT_POLICY_REQUIRED")
        policy_version = int(getattr(policy, "version", 0))
        payment_policy_ref = f"{PAYMENT_POLICY_KEY}@{policy_version}"
        permitted_methods = _permitted_methods(policy)
        selected = str(selected_method).strip().lower()
        if selected not in permitted_methods:
            raise C3Error("C4_PAYMENT_METHOD_NOT_PERMITTED", selected)
        mapping = _EXTERNAL_EXECUTION_METHODS.get(selected)
        if mapping is None:
            raise C3Error("C4_EXTERNAL_METHOD_REQUIRED", selected)
        payment_method_code, payment_rail_code = mapping

        business_time = BusinessTimeResolver.resolve(
            build_wnd_calendar(context.tenant_id),
            order.submitted_at,
        )
        intent_public_id = payment_intent_public_id(request_public_id)
        attempt_public_id = payment_attempt_public_id(request_public_id)
        correlation_id = finance_correlation_id(
            tenant_id=context.tenant_id,
            organization_unit_id=organization_unit_id,
            order_public_id=order.public_id,
            row_version=order.row_version,
        )
        identity_key = c4_idempotency_key(request_public_id)

        intent_command = CreatePaymentIntentCommand(
            public_id=intent_public_id,
            tenant_id=context.tenant_id,
            organization_unit_id=organization_unit_id,
            payment_request_public_id=request_public_id,
            requested_amount=request.requested_amount,
            currency_code=request.currency_code,
            payment_method_policy={
                "allowed_methods": [payment_method_code],
                "allow_mixed_tender": False,
                "max_tenders": 1,
            },
            expires_at=None,
            occurred_at=order.submitted_at,
            business_date=business_time.business_date,
            calendar_policy_version=business_time.calendar_version,
            correlation_id=correlation_id,
            actor_user_id=context.actor_user_id,
            actor_service=C4_ACTOR_SERVICE,
            source_component=C4_SOURCE_COMPONENT,
            source_record_id=f"payment_request:{request_public_id}",
            idempotency_scope=C4_INTENT_IDEMPOTENCY_SCOPE,
            idempotency_key=identity_key,
            metadata={
                "selected_method": selected,
                "payment_policy_ref": payment_policy_ref,
                "order_public_id": str(order.public_id),
            },
        )
        intent_result = self.finance.create_intent(session, intent_command)
        intent = intent_result.payment_intent
        if (
            intent.public_id != intent_public_id
            or intent.requested_amount != request.requested_amount
            or intent.currency_code != request.currency_code
        ):
            raise C3Error("C4_INTENT_AUTHORITY_MISMATCH")

        attempt_command = CreatePaymentAttemptCommand(
            public_id=attempt_public_id,
            tenant_id=context.tenant_id,
            organization_unit_id=organization_unit_id,
            payment_intent_public_id=intent_public_id,
            attempted_amount=request.requested_amount,
            currency_code=request.currency_code,
            payment_method_code=payment_method_code,
            payment_rail_code=payment_rail_code,
            orchestrator_code="xafpay",
            provider_account_public_id=None,
            underlying_provider_code=None,
            external_attempt_reference=None,
            timeout_at=None,
            occurred_at=order.submitted_at,
            business_date=business_time.business_date,
            calendar_policy_version=business_time.calendar_version,
            correlation_id=correlation_id,
            actor_user_id=context.actor_user_id,
            actor_service=C4_ACTOR_SERVICE,
            source_component=C4_SOURCE_COMPONENT,
            source_record_id=f"payment_intent:{intent_public_id}",
            idempotency_scope=C4_ATTEMPT_IDEMPOTENCY_SCOPE,
            idempotency_key=identity_key,
            metadata={
                "selected_method": selected,
                "payment_request_public_id": str(request_public_id),
                "order_public_id": str(order.public_id),
            },
        )
        attempt_result = self.finance.create_attempt(session, attempt_command)
        attempt = attempt_result.payment_attempt
        if (
            attempt.public_id != attempt_public_id
            or attempt.payment_method_code != payment_method_code
            or attempt.payment_rail_code != payment_rail_code
            or attempt.orchestrator_code != "xafpay"
            or attempt.provider_account_id is not None
            or attempt.underlying_provider_code is not None
        ):
            raise C3Error("C4_ATTEMPT_AUTHORITY_MISMATCH")

        gateway_request = self.gateway.prepare(
            session,
            tenant_id=context.tenant_id,
            organization_unit_id=organization_unit_id,
            payment_attempt_public_id=attempt_public_id,
            channel=channel,
        )
        expected_gateway_identity = f"xbos:pay:{attempt_public_id}"
        if (
            gateway_request.external_reference != expected_gateway_identity
            or gateway_request.idempotency_key != expected_gateway_identity
        ):
            raise C3Error("C4_GATEWAY_IDENTITY_MISMATCH")

        gateway_response = self.gateway.create(
            gateway_request,
            service_credential=service_credential,
            transport=transport,
        )
        recorded_attempt = self.gateway.record(
            session,
            RecordXafPayPaymentCreateCommand(
                tenant_id=context.tenant_id,
                organization_unit_id=organization_unit_id,
                payment_attempt_public_id=attempt_public_id,
                response=gateway_response,
                occurred_at=order.submitted_at,
                business_date=business_time.business_date,
                calendar_policy_version=business_time.calendar_version,
                correlation_id=correlation_id,
                actor_service=C4_ACTOR_SERVICE,
            ),
        )
        attempt_state = str(_record_value(recorded_attempt, "attempt_state"))
        if attempt_state not in {"processing", "requires_action"}:
            raise C3Error("C4_ATTEMPT_STATE_UNEXPECTED", attempt_state)
        external_attempt_reference = _record_value(recorded_attempt, "external_attempt_reference")
        if external_attempt_reference != gateway_response.payment_id:
            raise C3Error("C4_GATEWAY_PAYMENT_ID_NOT_RECORDED")

        return ExternalPaymentExecutionHandoffProjection(
            payment_request_ref=str(request_public_id),
            payment_intent_ref=str(intent_public_id),
            payment_attempt_ref=str(attempt_public_id),
            selected_method=selected,
            payment_method_code=payment_method_code,
            payment_rail_code=payment_rail_code,
            canonical_amount=request.requested_amount,
            currency=request.currency_code,
            gateway_payment_id=gateway_response.payment_id,
            gateway_external_reference=gateway_request.external_reference,
            gateway_idempotency_key=gateway_request.idempotency_key,
            gateway_status=gateway_response.status,
            attempt_state=attempt_state,
            next_action=gateway_response.next_action,
        )
