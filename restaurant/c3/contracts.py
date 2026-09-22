from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


PAYMENT_POLICY_KEY = "wnd.payments.enabled_methods"
PAYMENT_REQUEST_PURPOSE = "restaurant_order"
IDEMPOTENCY_SCOPE = "restaurant.c3.payment_request"
SOURCE_COMPONENT = "restaurant.c3"
ACTOR_SERVICE = "xbos.restaurant.c3"
SAFE_NEXT_ACTION = "present_permitted_methods_only"


class C3Error(ValueError):
    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


@dataclass(frozen=True, slots=True)
class TrustedCheckoutContext:
    """Server-derived XBOS scope. It is never a customer payload contract."""

    tenant_id: int
    branch_id: int
    actor_user_id: int | None = None

    def __post_init__(self) -> None:
        if int(self.tenant_id) <= 0 or int(self.branch_id) <= 0:
            raise C3Error("C3_TRUST_CONTEXT_REQUIRED", "positive tenant and branch are required")
        if self.actor_user_id is not None and int(self.actor_user_id) <= 0:
            raise C3Error("C3_ACTOR_USER_INVALID", "actor_user_id must be positive when present")


@dataclass(frozen=True, slots=True)
class WalletHandoffContext:
    payment_request_ref: str
    order_ref: str
    merchant_reference: str
    canonical_amount: Decimal
    currency: str
    correlation_ref: str
    policy_ref: str


@dataclass(frozen=True, slots=True)
class CustomerSafePaymentRequestProjection:
    payment_request_ref: str
    order_ref: str
    merchant_reference: str
    correlation_ref: str
    canonical_amount: Decimal
    currency: str
    permitted_methods: tuple[str, ...]
    policy_ref: str
    expires_at: datetime | None
    payment_request_state: str
    wallet_handoff_context: WalletHandoffContext | None
    safe_next_action: str
    receipt_ref: str | None
