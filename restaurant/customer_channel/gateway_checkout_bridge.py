from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from core.integrations.xafpay_v2.wnd_service import WndXafPayV2Service
from core.platform.operating_context import BusinessTimeResolver
from restaurant.c3.service import payment_request_public_id
from restaurant.r5 import build_wnd_calendar

from .contracts import H1BError, TrustedCheckoutScope

_METHOD_TO_RAIL = {
    "mtn_mobile_money": "mtn",
    "orange_money": "orange",
}


@dataclass(frozen=True, slots=True)
class VerifiedGatewayMerchantBinding:
    """Nonsecret app-level proof input; never contains the Gateway credential value."""

    tenant_id: int
    merchant_public_id: UUID
    gateway_merchant_id: str
    service_credential_reference: str
    verification_state: str = "verified"

    def __post_init__(self) -> None:
        object.__setattr__(self, "merchant_public_id", UUID(str(self.merchant_public_id)))
        object.__setattr__(self, "gateway_merchant_id", str(self.gateway_merchant_id).strip())
        object.__setattr__(
            self,
            "service_credential_reference",
            str(self.service_credential_reference).strip(),
        )
        object.__setattr__(
            self, "verification_state", str(self.verification_state).strip().lower()
        )
        if self.tenant_id <= 0:
            raise ValueError("WND_GATEWAY_BINDING_TENANT_INVALID")
        if not self.gateway_merchant_id.startswith("mch_"):
            raise ValueError("WND_GATEWAY_BINDING_MERCHANT_INVALID")
        if not self.service_credential_reference:
            raise ValueError("WND_GATEWAY_BINDING_CREDENTIAL_REFERENCE_REQUIRED")
        if self.service_credential_reference.startswith("xps_") or "." in self.service_credential_reference:
            raise ValueError("WND_GATEWAY_BINDING_MUST_NOT_CONTAIN_CREDENTIAL_SECRET")


class WNDGatewayCheckoutBridge:
    """Canonical WND order -> C3 request -> hosted Gateway checkout/status seam.

    This class does not load credentials, call providers directly, or decide merchant
    identity. A separately qualified runtime must inject a verified nonsecret binding
    plus an already-constructed CheckoutSession client.
    """

    @staticmethod
    def _assert_binding(
        scope: TrustedCheckoutScope, binding: VerifiedGatewayMerchantBinding
    ) -> None:
        if binding.verification_state != "verified":
            raise H1BError(
                "PAYMENT_OPTIONS_UNAVAILABLE", correlation_ref=scope.correlation_ref
            )
        if (
            binding.tenant_id != scope.tenant_id
            or binding.merchant_public_id != scope.merchant_public_id
        ):
            raise H1BError("CONTEXT_MISMATCH", correlation_ref=scope.correlation_ref)

    @staticmethod
    def _order(authority, scope: TrustedCheckoutScope, order_ref: UUID):
        order = authority.adapters.r1_repo.order(scope.tenant_id, UUID(str(order_ref)))
        if order is None:
            raise H1BError("UNKNOWN_ORDER_RESULT", correlation_ref=scope.correlation_ref)
        state = str(getattr(getattr(order, "status", None), "value", getattr(order, "status", "")))
        if state != "submitted" or getattr(order, "submitted_at", None) is None:
            raise H1BError("ORDER_NOT_READY", correlation_ref=scope.correlation_ref)
        return order

    @staticmethod
    def _source_context(authority, scope: TrustedCheckoutScope, order) -> tuple[UUID, int]:
        """Return WND-owned location and stable commercial source version."""

        location_public_id = authority.repo.location_public_id(
            scope.tenant_id, scope.location_id
        )
        draft = authority.repo.draft_by_order(scope.tenant_id, order.public_id)
        if draft is not None:
            version = int(draft.get("catalog_binding_version") or 0)
            if version <= 0:
                raise H1BError(
                    "ORDER_NOT_READY", correlation_ref=scope.correlation_ref
                )
            return location_public_id, version

        rows = authority.repo.session.execute(
            text(
                """
                SELECT authoritative_snapshot
                FROM restaurant_customer_order_confirmations
                WHERE tenant_id=:tenant AND order_public_id=:order_ref
                ORDER BY id
                """
            ),
            {"tenant": scope.tenant_id, "order_ref": str(order.public_id)},
        ).mappings().all()
        if len(rows) != 1:
            raise H1BError(
                "ORDER_NOT_READY", correlation_ref=scope.correlation_ref
            )
        snapshot = dict(rows[0]["authoritative_snapshot"] or {})
        if (
            int(snapshot.get("location_id") or 0) != scope.location_id
            or str(snapshot.get("merchant_ref") or "") != str(scope.merchant_public_id)
            or str(snapshot.get("context_binding_ref") or "")
            != str(scope.context_binding_public_id)
        ):
            raise H1BError(
                "CONTEXT_MISMATCH", correlation_ref=scope.correlation_ref
            )
        versions: list[int] = []
        for line in snapshot.get("lines") or ():
            for key in ("catalog_entry_version", "price_version"):
                try:
                    value = int(line.get(key) or 0)
                except (TypeError, ValueError):
                    value = 0
                if value > 0:
                    versions.append(value)
        if not versions:
            raise H1BError(
                "ORDER_NOT_READY", correlation_ref=scope.correlation_ref
            )
        return location_public_id, max(versions)

    @classmethod
    def initiate(
        cls,
        session,
        *,
        authority,
        scope: TrustedCheckoutScope,
        order_ref: UUID,
        selected_method: str,
        binding: VerifiedGatewayMerchantBinding,
        client,
    ) -> dict:
        cls._assert_binding(scope, binding)
        order = cls._order(authority, scope, order_ref)
        location_public_id, catalog_version = cls._source_context(authority, scope, order)
        payment = authority.create_payment_request(scope=scope, order_ref=order.public_id)

        if payment.get("order_ref") != str(order.public_id):
            raise H1BError(
                "UNKNOWN_PAYMENT_REQUEST_RESULT", correlation_ref=scope.correlation_ref
            )
        if payment.get("currency") != "XAF":
            raise H1BError(
                "PAYMENT_OPTIONS_UNAVAILABLE", correlation_ref=scope.correlation_ref
            )
        amount = Decimal(str(payment.get("canonical_amount")))
        if amount <= 0 or amount != amount.to_integral_value():
            raise H1BError(
                "PAYMENT_OPTIONS_UNAVAILABLE", correlation_ref=scope.correlation_ref
            )

        method = str(selected_method or "").strip().lower()
        permitted = tuple(str(x) for x in (payment.get("permitted_methods") or ()))
        if method not in permitted or method not in _METHOD_TO_RAIL:
            raise H1BError(
                "UNSUPPORTED_METHOD", correlation_ref=scope.correlation_ref
            )

        request_ref = UUID(str(payment["payment_request_ref"]))
        correlation_id = UUID(str(payment["correlation_ref"]))
        business_time = BusinessTimeResolver.resolve(
            build_wnd_calendar(scope.tenant_id), order.submitted_at
        )
        hosted = WndXafPayV2Service.initiate_canonical_order(
            session,
            tenant_id=scope.tenant_id,
            organization_unit_id=scope.organization_unit_id,
            merchant_public_id=scope.merchant_public_id,
            gateway_merchant_id=binding.gateway_merchant_id,
            service_credential_reference=binding.service_credential_reference,
            order_public_id=order.public_id,
            order_row_version=int(order.row_version),
            location_public_id=location_public_id,
            catalog_version=catalog_version,
            payment_request_public_id=request_ref,
            amount=amount,
            rail=_METHOD_TO_RAIL[method],
            occurred_at=order.submitted_at,
            business_date=business_time.business_date,
            calendar_policy_version=business_time.calendar_version,
            correlation_id=correlation_id,
            client=client,
        )
        if hosted["payment_request_ref"] != str(request_ref):
            raise H1BError(
                "UNKNOWN_PAYMENT_REQUEST_RESULT", correlation_ref=scope.correlation_ref
            )
        if hosted["order_ref"] != str(order.public_id):
            raise H1BError("UNKNOWN_ORDER_RESULT", correlation_ref=scope.correlation_ref)
        if Decimal(str(hosted["canonical_amount"])) != amount:
            raise H1BError(
                "UNKNOWN_PAYMENT_REQUEST_RESULT", correlation_ref=scope.correlation_ref
            )

        return {
            "order_ref": str(order.public_id),
            "merchant_reference": payment["merchant_reference"],
            "payment_request_ref": str(request_ref),
            "payment_attempt_ref": hosted["payment_attempt_ref"],
            "correlation_ref": payment["correlation_ref"],
            "canonical_amount": amount,
            "currency": "XAF",
            "selected_method": method,
            "checkout_session_id": hosted["checkout_session_id"],
            "checkout_token": hosted["checkout_token"],
            "presentation_state": hosted["presentation_state"],
            "checkout_status": hosted["checkout_status"],
            "payment_status": hosted["payment_status"],
            "paid": hosted["paid"],
            "can_fulfill": hosted["can_fulfill"],
        }

    @classmethod
    def status(
        cls,
        session,
        *,
        authority,
        scope: TrustedCheckoutScope,
        order_ref: UUID,
        binding: VerifiedGatewayMerchantBinding,
    ) -> dict:
        cls._assert_binding(scope, binding)
        order = cls._order(authority, scope, order_ref)
        location_public_id, catalog_version = cls._source_context(authority, scope, order)
        request_ref = payment_request_public_id(
            tenant_id=scope.tenant_id,
            organization_unit_id=scope.organization_unit_id,
            order_public_id=order.public_id,
            row_version=int(order.row_version),
        )
        status = WndXafPayV2Service.canonical_status(
            session,
            tenant_id=scope.tenant_id,
            organization_unit_id=scope.organization_unit_id,
            merchant_public_id=scope.merchant_public_id,
            gateway_merchant_id=binding.gateway_merchant_id,
            service_credential_reference=binding.service_credential_reference,
            order_public_id=order.public_id,
            order_row_version=int(order.row_version),
            location_public_id=location_public_id,
            catalog_version=catalog_version,
            payment_request_public_id=request_ref,
        )
        return {
            "order_ref": str(order.public_id),
            "payment_request_ref": str(request_ref),
            "payment_attempt_ref": status["payment_attempt_ref"],
            "canonical_amount": status["canonical_amount"],
            "currency": status["currency"],
            "payment_status": status["payment_status"],
            "paid": status["paid"],
            "can_fulfill": status["can_fulfill"],
            "checkout_status": status["checkout_status"],
        }

    @classmethod
    def merchant_reconciliation(
        cls,
        session,
        *,
        authority,
        scope: TrustedCheckoutScope,
        order_ref: UUID,
        binding: VerifiedGatewayMerchantBinding,
    ) -> dict:
        cls._assert_binding(scope, binding)
        order = cls._order(authority, scope, order_ref)
        location_public_id, catalog_version = cls._source_context(authority, scope, order)
        request_ref = payment_request_public_id(
            tenant_id=scope.tenant_id,
            organization_unit_id=scope.organization_unit_id,
            order_public_id=order.public_id,
            row_version=int(order.row_version),
        )
        status = WndXafPayV2Service.canonical_status(
            session,
            tenant_id=scope.tenant_id,
            organization_unit_id=scope.organization_unit_id,
            merchant_public_id=scope.merchant_public_id,
            gateway_merchant_id=binding.gateway_merchant_id,
            service_credential_reference=binding.service_credential_reference,
            order_public_id=order.public_id,
            order_row_version=int(order.row_version),
            location_public_id=location_public_id,
            catalog_version=catalog_version,
            payment_request_public_id=request_ref,
        )
        return {
            "order_ref": str(order.public_id),
            "order_state": "submitted",
            "payment_request_ref": str(request_ref),
            "payment_intent_ref": status["payment_intent_ref"],
            "payment_attempt_ref": status["payment_attempt_ref"],
            "gateway_merchant_id": binding.gateway_merchant_id,
            "gateway_payment_id": status["gateway_payment_id"],
            "checkout_session_id": status["checkout_session_id"],
            "checkout_status": status["checkout_status"],
            "attempt_state": status["attempt_state"],
            "confirmed_settlements": status["confirmed_settlements"],
            "canonical_amount": status["canonical_amount"],
            "currency": status["currency"],
            "payment_status": status["payment_status"],
            "paid": status["paid"],
            "can_fulfill": status["can_fulfill"],
            "reconciliation_state": (
                "CONFIRMED_MATCH"
                if status["paid"]
                else "PENDING_MATCH"
                if status["payment_status"] == "PAYMENT_PENDING"
                else "NOT_CONFIRMED"
            ),
        }
