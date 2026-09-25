from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

PRIVATE_ROUTE_PREFIX = "/internal/customer-channel/v1"
SERVICE_PRINCIPAL = "customer-channel"
CHECKOUT_PERMISSION = "restaurant.customer_channel.checkout"
CONTEXT_PURPOSE = "restaurant.customer_channel.checkout"
CONTACT_PURPOSE = "restaurant.customer_channel.contact"
DELIVERY_ADDRESS_PURPOSE = "restaurant.customer_channel.delivery_address"
SERVICE_CREDENTIAL_REFERENCE = "env.xafpay_customer_channel_service_token"
TOKEN_DIGEST_CURRENT_ENV = "XAFPAY_CUSTOMER_CHANNEL_SERVICE_TOKEN_SHA256_CURRENT"
TOKEN_DIGEST_NEXT_ENV = "XAFPAY_CUSTOMER_CHANNEL_SERVICE_TOKEN_SHA256_NEXT"
CONFIRMATION_TTL_SECONDS = 300
PRICE_CODE = "retail"

SAFE_MESSAGES = {
    "ORDER_NOT_READY": "The order cannot be prepared from the current restaurant configuration.",
    "ORDER_CONFIRMATION_EXPIRED_OR_CHANGED": "The order confirmation expired or changed. Please confirm the order again.",
    "PAYMENT_OPTIONS_UNAVAILABLE": "Payment options are not available for this order.",
    "CONTEXT_MISMATCH": "The checkout context is unavailable or no longer valid.",
    "UNKNOWN_ORDER_RESULT": "The submitted order result could not be recovered.",
    "UNKNOWN_PAYMENT_REQUEST_RESULT": "The payment request result could not be recovered.",
    "UNSUPPORTED_METHOD": "The requested checkout option is not supported.",
    "SERVICE_AUTH_REQUIRED": "Customer Channel service authentication is required.",
    "SERVICE_AUTH_FORBIDDEN": "Customer Channel service authentication is not authorized for this context.",
    "IDEMPOTENCY_CONFLICT": "The submission reference conflicts with an existing checkout attempt.",
}

_STATUS = {
    "SERVICE_AUTH_REQUIRED": 401,
    "SERVICE_AUTH_FORBIDDEN": 403,
    "CONTEXT_MISMATCH": 403,
    "UNKNOWN_ORDER_RESULT": 404,
    "UNKNOWN_PAYMENT_REQUEST_RESULT": 404,
    "IDEMPOTENCY_CONFLICT": 409,
    "ORDER_CONFIRMATION_EXPIRED_OR_CHANGED": 409,
    "ORDER_NOT_READY": 409,
    "PAYMENT_OPTIONS_UNAVAILABLE": 409,
    "UNSUPPORTED_METHOD": 422,
}


class H1BError(RuntimeError):
    def __init__(self, code: str, *, correlation_ref: str | None = None):
        if code not in SAFE_MESSAGES:
            code = "ORDER_NOT_READY"
        self.code = code
        self.safe_message = SAFE_MESSAGES[code]
        self.correlation_ref = correlation_ref
        self.status_code = _STATUS.get(code, 400)
        super().__init__(code)

    def envelope(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.safe_message,
                "correlation_ref": self.correlation_ref,
            }
        }


@dataclass(frozen=True, slots=True)
class ServiceAuthorization:
    service_identity_id: int
    service_identity_public_id: UUID
    tenant_id: int
    location_id: int
    rotation_slot: str


@dataclass(frozen=True, slots=True)
class TrustedCheckoutScope:
    tenant_id: int
    branch_id: int
    organization_unit_id: int
    location_id: int
    merchant_public_id: UUID
    context_binding_public_id: UUID
    service_identity_public_id: UUID
    currency: str
    correlation_ref: str


@dataclass(frozen=True, slots=True)
class BoundContact:
    binding_public_id: UUID
    contact_id: int
    party_public_id: UUID
    contact_type: str
    contact_value: str
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AuthoritativeLine:
    catalog_entry_ref: UUID
    target_type: str
    target_ref: UUID
    price_ref: UUID
    quantity: Decimal
    unit_price: Decimal
    currency: str
    catalog_entry_version: int
    price_version: int
    option_refs: tuple[UUID, ...] = ()
    modifier_selections: tuple[dict[str, Any], ...] = ()
    line_kind: str = "item"

    @property
    def total(self) -> Decimal:
        return self.quantity * self.unit_price


@dataclass(frozen=True, slots=True)
class DeliverySelection:
    policy_ref: UUID
    policy_version: int
    fee_line: AuthoritativeLine | None


@dataclass(frozen=True, slots=True)
class ConfirmationProjection:
    confirmation_ref: UUID
    merchant_ref: UUID
    location_ref: int
    service_context_ref: UUID
    service_mode: str
    authoritative_lines: tuple[AuthoritativeLine, ...]
    canonical_total: Decimal
    currency: str
    observed_quote_ref: str | None
    observed_quote_version: str | None
    policy_refs: tuple[str, ...]
    expires_at: datetime
    commercial_fingerprint: str


@dataclass(frozen=True, slots=True)
class OrderProjection:
    order_ref: UUID
    order_code: str
    order_state: str
    service_mode: str
    row_version: int


def payment_projection_dict(value: Any) -> dict[str, Any]:
    """Exact 13-field C3 customer-safe projection."""
    wallet = value.wallet_handoff_context
    wallet_value = None
    if wallet is not None:
        wallet_value = {
            "payment_request_ref": wallet.payment_request_ref,
            "order_ref": wallet.order_ref,
            "merchant_reference": wallet.merchant_reference,
            "canonical_amount": wallet.canonical_amount,
            "currency": wallet.currency,
            "correlation_ref": wallet.correlation_ref,
            "policy_ref": wallet.policy_ref,
        }
    return {
        "payment_request_ref": value.payment_request_ref,
        "order_ref": value.order_ref,
        "merchant_reference": value.merchant_reference,
        "correlation_ref": value.correlation_ref,
        "canonical_amount": value.canonical_amount,
        "currency": value.currency,
        "permitted_methods": list(value.permitted_methods),
        "policy_ref": value.policy_ref,
        "expires_at": value.expires_at,
        "payment_request_state": value.payment_request_state,
        "wallet_handoff_context": wallet_value,
        "safe_next_action": value.safe_next_action,
        "receipt_ref": value.receipt_ref,
    }
