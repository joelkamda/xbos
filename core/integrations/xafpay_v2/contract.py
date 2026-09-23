"""Typed, secret-free current Gateway CheckoutSession/event contracts at the XBOS boundary."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping
from uuid import UUID

_EXTERNAL = re.compile(r"^xbos:pay:([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$")
_GATEWAY_PAYMENT_ID = re.compile(r"^pay_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
_CHECKOUT_ID = re.compile(r"^chk_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
_REFUND_ID = re.compile(r"^rfd_[0-9a-f-]+$")
_REVERSAL_ID = re.compile(r"^rev_[0-9a-f-]+$")
_EVENT_ID = re.compile(r"^evt_[0-9a-f-]+$")
_CORRELATION_ID = re.compile(r"^cor_[0-9a-f-]+$")
_ALLOWED_PAYMENT_EVENTS = frozenset({
    "payment.created", "payment.requires_action", "payment.pending",
    "payment.succeeded", "payment.failed", "payment.canceled", "payment.expired",
})
_ALLOWED_EVENT_TYPES = _ALLOWED_PAYMENT_EVENTS | {"refund.succeeded", "payment.reversed"}
_PAYMENT_EVENT_STATUS = {
    "payment.created": "CREATED",
    "payment.requires_action": "REQUIRES_ACTION",
    "payment.pending": "PENDING",
    "payment.succeeded": "SUCCEEDED",
    "payment.failed": "FAILED",
    "payment.canceled": "CANCELED",
    "payment.expired": "EXPIRED",
}


class XafPayV2IntegrationError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _whole_xaf(value: Any) -> int:
    try:
        selected = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise XafPayV2IntegrationError("invalid_amount", "amount must be numeric") from exc
    if not selected.is_finite() or selected <= 0 or selected != selected.to_integral_value():
        raise XafPayV2IntegrationError("invalid_amount", "XAF amount must be a positive whole amount")
    integer = int(selected)
    if integer > 9_007_199_254_740_991:
        raise XafPayV2IntegrationError("invalid_amount", "amount exceeds Gateway safe integer range")
    return integer


@dataclass(frozen=True)
class XafPayV2CheckoutRequest:
    payment_attempt_public_id: UUID
    amount: Decimal
    currency_code: str
    payment_method_code: str
    payment_rail_code: str
    channel: str = "xbos"

    def __post_init__(self) -> None:
        object.__setattr__(self, "payment_attempt_public_id", UUID(str(self.payment_attempt_public_id)))
        object.__setattr__(self, "currency_code", str(self.currency_code).strip().upper())
        object.__setattr__(self, "payment_method_code", str(self.payment_method_code).strip().upper())
        object.__setattr__(self, "payment_rail_code", str(self.payment_rail_code).strip().upper())
        object.__setattr__(self, "channel", str(self.channel).strip().lower())
        if self.currency_code != "XAF":
            raise XafPayV2IntegrationError("unsupported_currency", "WND XafPay checkout requires XAF")
        _whole_xaf(self.amount)
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", self.payment_method_code):
            raise XafPayV2IntegrationError("invalid_method", "payment method code is invalid")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", self.payment_rail_code):
            raise XafPayV2IntegrationError("invalid_rail", "payment rail code is invalid")
        if not re.fullmatch(r"[a-z0-9][a-z0-9._:-]{0,63}", self.channel):
            raise XafPayV2IntegrationError("invalid_channel", "channel is invalid")

    @property
    def external_reference(self) -> str:
        return f"xbos:pay:{self.payment_attempt_public_id}"

    @property
    def idempotency_key(self) -> str:
        return f"xbos-checkout-{self.payment_attempt_public_id}"

    def body(self) -> dict[str, Any]:
        return {
            "external_reference": self.external_reference,
            "amount": {"minor": _whole_xaf(self.amount), "currency": self.currency_code},
            "permitted_options": [
                {"method": self.payment_method_code, "rail": self.payment_rail_code}
            ],
            "language": "en",
            "branding": {"profile": "default"},
            "expires_in_seconds": 1800,
            "channel": self.channel,
            "metadata": {"source": "xbos_xafpay_v2"},
        }


@dataclass(frozen=True)
class XafPayV2CheckoutResponse:
    checkout_session_id: str
    external_reference: str
    status: str
    amount_minor: int
    currency_code: str
    public_token: str | None
    presentation_state: str
    evidence: Mapping[str, Any]

    @classmethod
    def parse(cls, value: Any, request: XafPayV2CheckoutRequest) -> "XafPayV2CheckoutResponse":
        if not isinstance(value, dict):
            raise XafPayV2IntegrationError("invalid_checkout_response", "Gateway response must be an object")
        try:
            session_id = str(value["checkout_session_id"])
            external_reference = str(value["external_reference"])
            status = str(value["status"]).upper()
            amount = value["amount"]
            amount_minor = int(amount["minor"])
            currency = str(amount["currency"]).upper()
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise XafPayV2IntegrationError("invalid_checkout_response", "Gateway checkout response is incomplete") from exc
        if not _CHECKOUT_ID.fullmatch(session_id):
            raise XafPayV2IntegrationError("invalid_checkout_identity", "Gateway checkout identity is invalid")
        if external_reference != request.external_reference:
            raise XafPayV2IntegrationError("gateway_external_reference_mismatch", "Gateway external reference changed")
        if amount_minor != _whole_xaf(request.amount) or currency != request.currency_code:
            raise XafPayV2IntegrationError("gateway_amount_mismatch", "Gateway checkout amount/currency changed")
        options = value.get("permitted_options")
        expected = [{"method": request.payment_method_code, "rail": request.payment_rail_code}]
        if options != expected:
            raise XafPayV2IntegrationError("gateway_option_mismatch", "Gateway checkout method/rail changed")
        token_value = value.get("public_token")
        token = str(token_value).strip() if token_value else None
        if status == "EXPIRED":
            return cls(
                session_id, external_reference, status, amount_minor, currency,
                None, "PRESENTATION_EXPIRED", dict(value),
            )
        if status not in {"CREATED", "ACTIVE"}:
            raise XafPayV2IntegrationError(
                "checkout_not_presentable", f"Gateway checkout is not presentable: {status}"
            )
        if not token or not token.startswith("chkpub_"):
            raise XafPayV2IntegrationError("invalid_checkout_token", "Gateway checkout token is invalid")
        return cls(
            session_id, external_reference, status, amount_minor, currency,
            token, "PRESENTABLE", dict(value),
        )


@dataclass(frozen=True)
class XafPayV2Event:
    event_id: str
    event_type: str
    occurred_at: datetime
    aggregate_type: str
    aggregate_id: str
    merchant_id: str
    correlation_id: str
    causation_id: str | None
    payment_id: str
    payment_attempt_public_id: UUID | None
    external_reference: str | None
    amount_minor: int
    currency_code: str
    status: str | None
    requested_method: str | None
    requested_rail: str | None
    provider_reference: str | None
    correction_id: str | None
    data: Mapping[str, Any]
    envelope: Mapping[str, Any]


def payload_sha256(raw_body: bytes) -> str:
    return hashlib.sha256(raw_body).hexdigest()


def verify_gateway_signature(
    raw_body: bytes,
    headers: Mapping[str, str],
    secret: str,
    *,
    now: datetime | None = None,
    replay_window_seconds: int = 300,
) -> None:
    normalized = {str(k).lower(): str(v).strip() for k, v in headers.items()}
    event_id = normalized.get("x-xafpay-event-id", "")
    timestamp_text = normalized.get("x-xafpay-timestamp", "")
    supplied = normalized.get("x-xafpay-signature", "").lower()
    version = normalized.get("x-xafpay-signature-version", "")
    if not raw_body or not secret or not event_id or version != "1" or not supplied.startswith("v1="):
        raise XafPayV2IntegrationError("signature_invalid", "Gateway event signature headers are incomplete")
    try:
        timestamp = int(timestamp_text)
    except ValueError as exc:
        raise XafPayV2IntegrationError("signature_timestamp_invalid", "Gateway timestamp is invalid") from exc
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise XafPayV2IntegrationError("clock_invalid", "verification clock must be timezone-aware")
    if abs(int(current.timestamp()) - timestamp) > replay_window_seconds:
        raise XafPayV2IntegrationError("signature_replay_window", "Gateway event timestamp is outside replay window")
    canonical = f"v1.{timestamp}.{event_id}.{payload_sha256(raw_body)}".encode("utf-8")
    expected = "v1=" + hmac.new(secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, supplied):
        raise XafPayV2IntegrationError("signature_invalid", "Gateway event signature does not match")


def parse_gateway_event(raw_body: bytes, headers: Mapping[str, str]) -> XafPayV2Event:
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise XafPayV2IntegrationError("event_json_invalid", "Gateway event is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise XafPayV2IntegrationError("event_envelope_invalid", "Gateway event must be an object")
    required = {
        "id", "type", "version", "occurred_at", "aggregate_type", "aggregate_id",
        "merchant_id", "correlation_id", "causation_id", "data",
    }
    if set(payload) != required:
        raise XafPayV2IntegrationError("event_envelope_invalid", "Gateway event envelope shape differs from current contract")
    normalized_headers = {str(k).lower(): str(v).strip() for k, v in headers.items()}
    event_id = str(payload.get("id", ""))
    event_type = str(payload.get("type", ""))
    if not _EVENT_ID.fullmatch(event_id) or normalized_headers.get("x-xafpay-event-id") != event_id:
        raise XafPayV2IntegrationError("event_identity_mismatch", "event id/header identity mismatch")
    if event_type not in _ALLOWED_EVENT_TYPES or payload.get("version") != 1:
        raise XafPayV2IntegrationError("event_contract_invalid", "event type/version differs from current contract")
    aggregate_type = str(payload.get("aggregate_type", ""))
    expected_aggregate = (
        "Refund" if event_type == "refund.succeeded"
        else "Reversal" if event_type == "payment.reversed"
        else "Payment"
    )
    if aggregate_type != expected_aggregate:
        raise XafPayV2IntegrationError("event_contract_invalid", "event aggregate differs from current contract")
    aggregate_id = str(payload.get("aggregate_id", ""))
    if aggregate_type == "Payment" and not _GATEWAY_PAYMENT_ID.fullmatch(aggregate_id):
        raise XafPayV2IntegrationError("event_aggregate_invalid", "payment aggregate id is invalid")
    if aggregate_type == "Refund" and not _REFUND_ID.fullmatch(aggregate_id):
        raise XafPayV2IntegrationError("event_aggregate_invalid", "refund aggregate id is invalid")
    if aggregate_type == "Reversal" and not _REVERSAL_ID.fullmatch(aggregate_id):
        raise XafPayV2IntegrationError("event_aggregate_invalid", "reversal aggregate id is invalid")
    correlation_id = str(payload.get("correlation_id", ""))
    if not _CORRELATION_ID.fullmatch(correlation_id):
        raise XafPayV2IntegrationError("event_correlation_invalid", "event correlation id is invalid")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise XafPayV2IntegrationError("event_data_invalid", "event data must be an object")
    forbidden = {"tenant_id", "tenant", "organization_unit_id", "location_id", "branch_id", "user_id", "role"}
    if forbidden.intersection(data):
        raise XafPayV2IntegrationError("gateway_scope_authority_violation", "Gateway event carries XBOS scope authority")

    payment_id = str(data.get("payment_id", ""))
    if not _GATEWAY_PAYMENT_ID.fullmatch(payment_id):
        raise XafPayV2IntegrationError("payment_identity_mismatch", "Gateway payment identity is invalid")
    if aggregate_type == "Payment" and payment_id != aggregate_id:
        raise XafPayV2IntegrationError("payment_identity_mismatch", "Gateway payment identity changed")

    external_reference: str | None = None
    attempt_public_id: UUID | None = None
    if aggregate_type in {"Payment", "Refund"}:
        external_reference = str(data.get("external_reference", ""))
        match = _EXTERNAL.fullmatch(external_reference)
        if not match:
            raise XafPayV2IntegrationError("external_reference_invalid", "Gateway external reference is invalid")
        attempt_public_id = UUID(match.group(1))

    correction_id: str | None = None
    if aggregate_type == "Refund":
        correction_id = str(data.get("refund_id", ""))
        if correction_id != aggregate_id:
            raise XafPayV2IntegrationError("refund_identity_mismatch", "Gateway refund identity changed")
    elif aggregate_type == "Reversal":
        correction_id = str(data.get("reversal_id", ""))
        if correction_id != aggregate_id:
            raise XafPayV2IntegrationError("reversal_identity_mismatch", "Gateway reversal identity changed")

    amount = data.get("amount")
    if not isinstance(amount, dict):
        raise XafPayV2IntegrationError("event_amount_invalid", "Gateway event amount is missing")
    try:
        amount_minor = int(amount["minor"])
        currency = str(amount["currency"]).upper()
    except (KeyError, TypeError, ValueError) as exc:
        raise XafPayV2IntegrationError("event_amount_invalid", "Gateway event amount is invalid") from exc
    if amount_minor <= 0 or currency != "XAF":
        raise XafPayV2IntegrationError("event_amount_invalid", "Gateway event amount/currency is invalid")
    try:
        occurred_at = datetime.fromisoformat(str(payload["occurred_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise XafPayV2IntegrationError("event_time_invalid", "event occurred_at is invalid") from exc
    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise XafPayV2IntegrationError("event_time_invalid", "event occurred_at must be timezone-aware")

    status_value = data.get("status")
    status = str(status_value).upper() if status_value is not None else None
    if event_type in _PAYMENT_EVENT_STATUS and status != _PAYMENT_EVENT_STATUS[event_type]:
        raise XafPayV2IntegrationError("event_status_mismatch", "Gateway event status does not match event type")
    if event_type == "refund.succeeded" and status != "SUCCEEDED":
        raise XafPayV2IntegrationError("event_status_mismatch", "Gateway refund status does not match event type")

    requested_method = data.get("requested_method")
    requested_rail = data.get("requested_rail")
    requested_method = str(requested_method).upper() if requested_method is not None else None
    requested_rail = str(requested_rail).upper() if requested_rail is not None else None
    provider_reference_value = data.get("provider_reference")
    provider_reference = str(provider_reference_value).strip() if provider_reference_value else None
    if event_type in {"payment.succeeded", "payment.reversed"} and not provider_reference:
        raise XafPayV2IntegrationError("provider_reference_required", "terminal provider evidence is required")

    return XafPayV2Event(
        event_id=event_id,
        event_type=event_type,
        occurred_at=occurred_at,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        merchant_id=str(payload["merchant_id"]),
        correlation_id=correlation_id,
        causation_id=str(payload["causation_id"]) if payload["causation_id"] is not None else None,
        payment_id=payment_id,
        payment_attempt_public_id=attempt_public_id,
        external_reference=external_reference,
        amount_minor=amount_minor,
        currency_code=currency,
        status=status,
        requested_method=requested_method,
        requested_rail=requested_rail,
        provider_reference=provider_reference,
        correction_id=correction_id,
        data=dict(data),
        envelope=dict(payload),
    )
