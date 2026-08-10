"""Typed, secret-free contracts at the XBOS/XafPay integration boundary."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping
from uuid import UUID


class XafPayIntegrationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _uuid(value: Any, name: str) -> UUID:
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise XafPayIntegrationError(f"invalid_{name}", f"{name} must be a UUID") from exc


def _timestamp(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise XafPayIntegrationError(f"invalid_{name}", f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _money(value: Any) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise XafPayIntegrationError("invalid_amount", "amount is invalid") from exc
    if not amount.is_finite() or amount <= 0 or amount != amount.to_integral_value():
        raise XafPayIntegrationError("invalid_xaf_amount", "XafPay requires a positive whole-XAF amount")
    return amount


def _text(value: Any, name: str, limit: int = 255) -> str:
    selected = str(value).strip()
    if not selected or len(selected) > limit:
        raise XafPayIntegrationError(f"invalid_{name}", f"{name} is blank or too long")
    return selected


@dataclass(frozen=True)
class XafPayInitiationRequest:
    payment_attempt_public_id: UUID
    amount: Decimal
    currency_code: str
    payment_rail_code: str
    customer_phone: str
    return_url: str
    cancel_url: str
    idempotency_key: str
    description: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "payment_attempt_public_id", _uuid(self.payment_attempt_public_id, "payment_attempt_public_id"))
        object.__setattr__(self, "amount", _money(self.amount))
        currency = _text(self.currency_code, "currency_code", 3).upper()
        if currency != "XAF":
            raise XafPayIntegrationError("unsupported_currency", "the XafPay adapter currently accepts XAF only")
        object.__setattr__(self, "currency_code", currency)
        rail = _text(self.payment_rail_code, "payment_rail_code", 64).lower()
        if rail not in {"mtn_momo", "orange_money"}:
            raise XafPayIntegrationError("unsupported_rail", "XafPay rail must be mtn_momo or orange_money")
        object.__setattr__(self, "payment_rail_code", rail)
        object.__setattr__(self, "customer_phone", _text(self.customer_phone, "customer_phone", 32))
        object.__setattr__(self, "return_url", _text(self.return_url, "return_url", 2048))
        object.__setattr__(self, "cancel_url", _text(self.cancel_url, "cancel_url", 2048))
        object.__setattr__(self, "idempotency_key", _text(self.idempotency_key, "idempotency_key", 200))
        if self.description is not None:
            object.__setattr__(self, "description", _text(self.description, "description", 500))


@dataclass(frozen=True)
class XafPayInitiationResponse:
    gateway_intent_id: UUID
    status: str
    payment_url: str | None
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "gateway_intent_id", _uuid(self.gateway_intent_id, "gateway_intent_id"))
        object.__setattr__(self, "status", _text(self.status, "status", 64).lower())
        if self.payment_url is not None:
            object.__setattr__(self, "payment_url", _text(self.payment_url, "payment_url", 2048))
        try:
            json.dumps(self.evidence, sort_keys=True)
        except (TypeError, ValueError) as exc:
            raise XafPayIntegrationError("invalid_evidence", "response evidence must be JSON serializable") from exc


@dataclass(frozen=True)
class RecordXafPayInitiationCommand:
    tenant_id: int
    organization_unit_id: int
    payment_attempt_public_id: UUID
    response: XafPayInitiationResponse
    occurred_at: datetime
    business_date: date
    calendar_policy_version: int
    correlation_id: UUID
    actor_service: str = "xbos.xafpay"

    def __post_init__(self) -> None:
        if self.tenant_id <= 0 or self.organization_unit_id <= 0 or self.calendar_policy_version <= 0:
            raise XafPayIntegrationError("invalid_scope", "tenant, organization, and calendar version must be positive")
        object.__setattr__(self, "payment_attempt_public_id", _uuid(self.payment_attempt_public_id, "payment_attempt_public_id"))
        object.__setattr__(self, "correlation_id", _uuid(self.correlation_id, "correlation_id"))
        object.__setattr__(self, "occurred_at", _timestamp(self.occurred_at, "occurred_at"))
        object.__setattr__(self, "actor_service", _text(self.actor_service, "actor_service", 120))


@dataclass(frozen=True)
class ProcessXafPayCallbackCommand:
    tenant_id: int
    organization_unit_id: int
    provider_account_public_id: UUID
    operational_account_public_id: UUID
    raw_body: bytes
    headers: Mapping[str, str]
    callback_secret: str
    received_at: datetime
    business_date: date
    calendar_policy_version: int
    correlation_id: UUID
    actor_service: str = "xbos.xafpay"

    def __post_init__(self) -> None:
        if self.tenant_id <= 0 or self.organization_unit_id <= 0 or self.calendar_policy_version <= 0:
            raise XafPayIntegrationError("invalid_scope", "tenant, organization, and calendar version must be positive")
        object.__setattr__(self, "provider_account_public_id", _uuid(self.provider_account_public_id, "provider_account_public_id"))
        object.__setattr__(self, "operational_account_public_id", _uuid(self.operational_account_public_id, "operational_account_public_id"))
        object.__setattr__(self, "correlation_id", _uuid(self.correlation_id, "correlation_id"))
        if not isinstance(self.raw_body, bytes) or not self.raw_body:
            raise XafPayIntegrationError("raw_body_required", "callback verification requires exact non-empty raw bytes")
        object.__setattr__(self, "headers", {str(k).lower(): str(v).strip() for k, v in self.headers.items()})
        object.__setattr__(self, "callback_secret", _text(self.callback_secret, "callback_secret", 4096))
        object.__setattr__(self, "received_at", _timestamp(self.received_at, "received_at"))
        object.__setattr__(self, "actor_service", _text(self.actor_service, "actor_service", 120))


@dataclass(frozen=True)
class NormalizedXafPayCallback:
    provider_event_reference: str
    payload_hash: str
    payment_attempt_public_id: UUID
    gateway_intent_id: UUID
    status: str
    amount: Decimal
    currency_code: str
    provider_code: str
    provider_reference: str
    occurred_at: datetime
    evidence: Mapping[str, Any]


@dataclass(frozen=True)
class XafPayCallbackResult:
    callback_public_id: UUID
    processing_state: str
    attempt_state: str | None
    settlement_public_id: UUID | None = None
    replayed: bool = False
