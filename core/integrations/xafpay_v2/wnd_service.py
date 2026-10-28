"""WND adapter into the current CheckoutSession-first XafPay product boundary."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

from core.domain.finance.payment_attempt_contract import CreatePaymentAttemptCommand
from core.domain.finance.payment_attempt_engine import TransactionalPaymentAttemptEngine
from core.domain.finance.payment_intent_contract import CreatePaymentIntentCommand
from core.domain.finance.payment_intent_engine import TransactionalPaymentIntentEngine
from core.domain.finance.payment_tender_contract import CreatePaymentTenderCommand
from core.domain.finance.payment_tender_engine import TransactionalPaymentTenderEngine

from .client import XafPayV2Client
from .contract import (
    WndMerchantCheckoutRequest,
    XafPayV2CheckoutRequest,
    XafPayV2IntegrationError,
)
from .service import XafPayV2Service


def _stable(kind: str, tenant_id: int, order_id: int, sale_id: int, generation: str) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"xbos:xafpay:current:{kind}:{tenant_id}:{order_id}:{sale_id}:{generation}",
    )


def _rail(value: str) -> str:
    normalized = str(value or "").strip().lower().replace("-", "_")
    mapping = {
        "mtn": "MTN_MOMO",
        "mtn_momo": "MTN_MOMO",
        "orange": "ORANGE_MONEY",
        "orange_money": "ORANGE_MONEY",
    }
    selected = mapping.get(normalized)
    if selected is None:
        raise ValueError("XAFPAY_WND_RAIL_UNSUPPORTED")
    return selected


class WndXafPayV2Service:
    """Creates only XBOS authority + one idempotent Gateway CheckoutSession."""

    @classmethod
    def initiate_order(
        cls,
        session,
        *,
        tenant_id: int,
        organization_unit_id: int,
        order_id: int,
        sale_id: int,
        amount: Decimal,
        rail: str,
        client: XafPayV2Client,
    ) -> dict:
        selected_amount = Decimal(amount)
        if selected_amount <= 0 or selected_amount != selected_amount.to_integral_value():
            raise ValueError("XAFPAY_WND_AMOUNT_MUST_BE_POSITIVE_WHOLE_XAF")
        rail_code = _rail(rail)

        prior = XafPayV2Service.repository.latest_attempt_for_order(
            session, tenant_id, order_id
        )
        if prior is not None:
            if (
                prior.tenant_id != tenant_id
                or prior.organization_unit_id != organization_unit_id
                or prior.attempted_amount != selected_amount
                or prior.currency_code.upper() != "XAF"
                or prior.payment_method_code.lower() != "mobile_money"
                or prior.payment_rail_code.upper() != rail_code
                or prior.metadata.get("order_id") != order_id
                or prior.metadata.get("sale_id") != sale_id
            ):
                raise RuntimeError("XAFPAY_WND_ATTEMPT_IDEMPOTENCY_CONFLICT")
            if prior.attempt_state == "succeeded":
                raise RuntimeError("XAFPAY_WND_OBLIGATION_ALREADY_SETTLED")
            if prior.attempt_state in {"failed", "cancelled", "expired"}:
                attempt = cls._create_retry_attempt(
                    session,
                    prior=prior,
                    amount=selected_amount,
                    rail_code=rail_code,
                    order_id=order_id,
                    sale_id=sale_id,
                )
            else:
                attempt = prior
        else:
            attempt = cls._create_initial_attempt(
                session,
                tenant_id=tenant_id,
                organization_unit_id=organization_unit_id,
                order_id=order_id,
                sale_id=sale_id,
                amount=selected_amount,
                rail_code=rail_code,
            )

        request = XafPayV2CheckoutRequest(
            payment_attempt_public_id=attempt.public_id,
            amount=attempt.attempted_amount,
            currency_code=attempt.currency_code,
            payment_method_code=attempt.payment_method_code,
            payment_rail_code=attempt.payment_rail_code,
            channel="xbos",
        )
        checkout = client.create_checkout(request)
        attempt = XafPayV2Service.repository.bind_checkout_session(
            session,
            attempt,
            checkout_session_id=checkout.checkout_session_id,
            checkout_status=checkout.status,
        )
        if XafPayV2Service.repository.settlement_count_for_attempt(
            session,
            tenant_id=attempt.tenant_id,
            attempt_public_id=attempt.public_id,
        ) != 0 and attempt.attempt_state != "succeeded":
            raise RuntimeError("XAFPAY_WND_CHECKOUT_CREATED_SETTLEMENT")

        return {
            "order_id": order_id,
            "sale_id": sale_id,
            "intent_public_id": str(attempt.payment_intent_public_id),
            "tender_public_id": (
                str(attempt.payment_tender_public_id)
                if attempt.payment_tender_public_id
                else None
            ),
            "attempt_public_id": str(attempt.public_id),
            "checkout_session_id": checkout.checkout_session_id,
            "checkout_token": checkout.public_token,
            "presentation_state": checkout.presentation_state,
            "checkout_status": checkout.status,
            "gateway_payment_id": attempt.external_attempt_reference,
            "status": (
                "PRESENTATION_EXPIRED"
                if checkout.presentation_state == "PRESENTATION_EXPIRED"
                else attempt.attempt_state.upper()
            ),
        }

    @classmethod
    def _create_initial_attempt(
        cls,
        session,
        *,
        tenant_id: int,
        organization_unit_id: int,
        order_id: int,
        sale_id: int,
        amount: Decimal,
        rail_code: str,
    ):
        now = datetime.now(timezone.utc)
        generation = "initial"
        intent_id = _stable("intent", tenant_id, order_id, sale_id, generation)
        tender_id = _stable("tender", tenant_id, order_id, sale_id, generation)
        attempt_id = _stable("attempt", tenant_id, order_id, sale_id, generation)
        correlation_id = _stable("correlation", tenant_id, order_id, sale_id, generation)
        scope = f"wnd.xafpay:{tenant_id}:{order_id}:{sale_id}"

        intent = TransactionalPaymentIntentEngine.create_intent(
            session,
            CreatePaymentIntentCommand(
                public_id=intent_id,
                tenant_id=tenant_id,
                organization_unit_id=organization_unit_id,
                requested_amount=amount,
                currency_code="XAF",
                payment_method_policy={
                    "allowed_methods": ["mobile_money"],
                    "allow_mixed_tender": False,
                    "max_tenders": 1,
                },
                occurred_at=now,
                business_date=now.date(),
                calendar_policy_version=1,
                correlation_id=correlation_id,
                actor_service="wnd.xafpay_v2",
                source_component="wnd.payment",
                source_record_id=f"order:{order_id}",
                idempotency_scope="wnd.xafpay_v2.intent",
                idempotency_key=f"{scope}:intent",
                metadata={
                    "order_id": order_id,
                    "sale_id": sale_id,
                    "authority": "XBOS",
                },
            ),
        ).payment_intent

        tender = TransactionalPaymentTenderEngine.create(
            session,
            CreatePaymentTenderCommand(
                public_id=tender_id,
                tenant_id=tenant_id,
                organization_unit_id=organization_unit_id,
                payment_intent_public_id=intent.public_id,
                tender_number=1,
                tender_amount=amount,
                currency_code="XAF",
                payment_method_code="mobile_money",
                occurred_at=now,
                business_date=now.date(),
                calendar_policy_version=1,
                correlation_id=correlation_id,
                actor_service="wnd.xafpay_v2",
                source_component="wnd.payment",
                source_record_id=f"order:{order_id}:tender",
                idempotency_scope="wnd.xafpay_v2.tender",
                idempotency_key=f"{scope}:tender",
                metadata={
                    "order_id": order_id,
                    "sale_id": sale_id,
                    "rail": rail_code,
                    "authority": "XBOS",
                },
            ),
        ).tender

        return TransactionalPaymentAttemptEngine.create(
            session,
            CreatePaymentAttemptCommand(
                public_id=attempt_id,
                tenant_id=tenant_id,
                organization_unit_id=organization_unit_id,
                payment_intent_public_id=intent.public_id,
                payment_tender_public_id=tender.public_id,
                attempted_amount=amount,
                currency_code="XAF",
                payment_method_code="mobile_money",
                payment_rail_code=rail_code,
                orchestrator_code="xafpay",
                provider_account_public_id=None,
                underlying_provider_code=None,
                occurred_at=now,
                business_date=now.date(),
                calendar_policy_version=1,
                correlation_id=correlation_id,
                timeout_at=now + timedelta(minutes=30),
                actor_service="wnd.xafpay_v2",
                source_component="wnd.payment",
                source_record_id=f"order:{order_id}:attempt",
                idempotency_scope="wnd.xafpay_v2.attempt",
                idempotency_key=f"{scope}:attempt",
                metadata={
                    "order_id": order_id,
                    "sale_id": sale_id,
                    "authority": "GATEWAY_EXECUTION",
                },
            ),
        ).payment_attempt

    @classmethod
    def _create_retry_attempt(
        cls,
        session,
        *,
        prior,
        amount: Decimal,
        rail_code: str,
        order_id: int,
        sale_id: int,
    ):
        if prior.payment_tender_public_id is None:
            raise XafPayV2IntegrationError(
                "payment_tender_not_found",
                "retry requires the original XafPay tender",
            )
        generation = f"retry:{prior.public_id}"
        now = datetime.now(timezone.utc)
        attempt_id = _stable(
            "attempt",
            prior.tenant_id,
            order_id,
            sale_id,
            generation,
        )
        correlation_id = _stable(
            "correlation",
            prior.tenant_id,
            order_id,
            sale_id,
            generation,
        )
        return TransactionalPaymentAttemptEngine.create(
            session,
            CreatePaymentAttemptCommand(
                public_id=attempt_id,
                tenant_id=prior.tenant_id,
                organization_unit_id=prior.organization_unit_id,
                payment_intent_public_id=prior.payment_intent_public_id,
                payment_tender_public_id=prior.payment_tender_public_id,
                attempted_amount=amount,
                currency_code="XAF",
                payment_method_code="mobile_money",
                payment_rail_code=rail_code,
                orchestrator_code="xafpay",
                provider_account_public_id=None,
                underlying_provider_code=None,
                retry_of_attempt_public_id=prior.public_id,
                occurred_at=now,
                business_date=prior.business_date,
                calendar_policy_version=prior.calendar_policy_version,
                correlation_id=correlation_id,
                timeout_at=now + timedelta(minutes=30),
                actor_service="wnd.xafpay_v2",
                source_component="wnd.payment",
                source_record_id=f"order:{order_id}:attempt:retry",
                idempotency_scope="wnd.xafpay_v2.attempt.retry",
                idempotency_key=f"wnd.xafpay:{prior.public_id}:retry",
                metadata={
                    "order_id": order_id,
                    "sale_id": sale_id,
                    "authority": "GATEWAY_EXECUTION",
                },
            ),
        ).payment_attempt


    @staticmethod
    def _canonical_intent_id(payment_request_public_id: UUID) -> UUID:
        return uuid5(
            NAMESPACE_URL,
            f"xbos:restaurant:c4:intent:{UUID(str(payment_request_public_id))}",
        )

    @staticmethod
    def _canonical_attempt_id(payment_request_public_id: UUID) -> UUID:
        return uuid5(
            NAMESPACE_URL,
            f"xbos:restaurant:c4:attempt:{UUID(str(payment_request_public_id))}",
        )

    @staticmethod
    def _validate_canonical_metadata(
        attempt,
        *,
        order_public_id: UUID,
        order_row_version: int,
        payment_request_public_id: UUID,
        merchant_public_id: UUID,
        gateway_merchant_id: str,
        service_credential_reference: str,
        location_public_id: UUID,
        catalog_version: int,
    ) -> None:
        metadata = dict(attempt.metadata or {})
        expected = {
            "order_public_id": str(UUID(str(order_public_id))),
            "order_row_version": int(order_row_version),
            "payment_request_public_id": str(UUID(str(payment_request_public_id))),
            "merchant_public_id": str(UUID(str(merchant_public_id))),
            "gateway_merchant_id": str(gateway_merchant_id),
            "service_credential_reference": str(service_credential_reference),
            "wnd_location_public_id": str(UUID(str(location_public_id))),
            "wnd_catalog_version": int(catalog_version),
        }
        for key, value in expected.items():
            if metadata.get(key) != value:
                raise RuntimeError("XAFPAY_WND_CANONICAL_BINDING_CONFLICT")

    @classmethod
    def initiate_canonical_order(
        cls,
        session,
        *,
        tenant_id: int,
        organization_unit_id: int,
        merchant_public_id: UUID,
        gateway_merchant_id: str,
        service_credential_reference: str,
        order_public_id: UUID,
        order_row_version: int,
        location_public_id: UUID,
        catalog_version: int,
        payment_request_public_id: UUID,
        amount: Decimal,
        rail: str,
        occurred_at,
        business_date,
        calendar_policy_version: int,
        correlation_id: UUID,
        client: XafPayV2Client,
    ) -> dict:
        """Create/replay one canonical UUID-bound hosted checkout.

        The Gateway credential value is held only by the injected client. This
        source stores only the independently qualified nonsecret credential
        reference and Gateway merchant identity used for reconciliation.
        """

        order_ref = UUID(str(order_public_id))
        merchant_ref = UUID(str(merchant_public_id))
        location_ref = UUID(str(location_public_id))
        request_ref = UUID(str(payment_request_public_id))
        correlation_ref = UUID(str(correlation_id))
        selected_amount = Decimal(amount)
        if (
            tenant_id <= 0
            or organization_unit_id <= 0
            or order_row_version <= 0
            or catalog_version <= 0
        ):
            raise ValueError("XAFPAY_WND_CANONICAL_SCOPE_INVALID")
        if selected_amount <= 0 or selected_amount != selected_amount.to_integral_value():
            raise ValueError("XAFPAY_WND_AMOUNT_MUST_BE_POSITIVE_WHOLE_XAF")
        if not str(gateway_merchant_id).startswith("mch_"):
            raise ValueError("XAFPAY_WND_GATEWAY_MERCHANT_REQUIRED")
        credential_ref = str(service_credential_reference or "").strip()
        if (
            not credential_ref
            or credential_ref.startswith("xps_")
            or "." in credential_ref
        ):
            raise ValueError("XAFPAY_WND_CREDENTIAL_REFERENCE_INVALID")
        rail_code = _rail(rail).lower()

        intent_id = cls._canonical_intent_id(request_ref)
        attempt_id = cls._canonical_attempt_id(request_ref)
        identity_key = f"request:{request_ref}"
        source_record = f"restaurant_order:{order_ref}:v{order_row_version}"
        common_metadata = {
            "order_public_id": str(order_ref),
            "order_row_version": int(order_row_version),
            "payment_request_public_id": str(request_ref),
            "merchant_public_id": str(merchant_ref),
            "gateway_merchant_id": str(gateway_merchant_id),
            "service_credential_reference": credential_ref,
            "wnd_location_public_id": str(location_ref),
            "wnd_catalog_version": int(catalog_version),
            "authority": "GATEWAY_EXECUTION",
        }

        intent = TransactionalPaymentIntentEngine.create_intent(
            session,
            CreatePaymentIntentCommand(
                public_id=intent_id,
                tenant_id=tenant_id,
                organization_unit_id=organization_unit_id,
                payment_request_public_id=request_ref,
                requested_amount=selected_amount,
                currency_code="XAF",
                payment_method_policy={
                    "allowed_methods": ["mobile_money"],
                    "allow_mixed_tender": False,
                    "max_tenders": 1,
                },
                expires_at=None,
                occurred_at=occurred_at,
                business_date=business_date,
                calendar_policy_version=calendar_policy_version,
                correlation_id=correlation_ref,
                actor_service="wnd.customer_channel.hosted_checkout",
                source_component="wnd.customer_channel.hosted_checkout",
                source_record_id=source_record,
                idempotency_scope="wnd.xafpay_v2.canonical.intent",
                idempotency_key=identity_key,
                metadata=common_metadata,
            ),
        ).payment_intent
        if (
            UUID(str(intent.public_id)) != intent_id
            or Decimal(intent.requested_amount) != selected_amount
            or str(intent.currency_code).upper() != "XAF"
        ):
            raise RuntimeError("XAFPAY_WND_CANONICAL_INTENT_MISMATCH")

        TransactionalPaymentAttemptEngine.create(
            session,
            CreatePaymentAttemptCommand(
                public_id=attempt_id,
                tenant_id=tenant_id,
                organization_unit_id=organization_unit_id,
                payment_intent_public_id=intent_id,
                payment_tender_public_id=None,
                attempted_amount=selected_amount,
                currency_code="XAF",
                payment_method_code="mobile_money",
                payment_rail_code=rail_code,
                orchestrator_code="xafpay",
                provider_account_public_id=None,
                underlying_provider_code=None,
                external_attempt_reference=None,
                timeout_at=occurred_at + timedelta(minutes=30),
                occurred_at=occurred_at,
                business_date=business_date,
                calendar_policy_version=calendar_policy_version,
                correlation_id=correlation_ref,
                actor_service="wnd.customer_channel.hosted_checkout",
                source_component="wnd.customer_channel.hosted_checkout",
                source_record_id=f"payment_request:{request_ref}",
                idempotency_scope="wnd.xafpay_v2.canonical.attempt",
                idempotency_key=identity_key,
                metadata=common_metadata,
            ),
        )

        attempt = XafPayV2Service.repository.attempt_authority(
            session, attempt_id, lock=True
        )
        if attempt is None:
            raise RuntimeError("XAFPAY_WND_CANONICAL_ATTEMPT_MISSING")
        if (
            attempt.tenant_id != tenant_id
            or attempt.organization_unit_id != organization_unit_id
            or attempt.payment_intent_public_id != intent_id
            or attempt.attempted_amount != selected_amount
            or attempt.currency_code.upper() != "XAF"
            or attempt.payment_method_code.lower() != "mobile_money"
            or attempt.payment_rail_code.lower() != rail_code
            or attempt.orchestrator_code != "xafpay"
            or attempt.provider_account_id is not None
            or attempt.underlying_provider_code is not None
        ):
            raise RuntimeError("XAFPAY_WND_CANONICAL_ATTEMPT_MISMATCH")
        cls._validate_canonical_metadata(
            attempt,
            order_public_id=order_ref,
            order_row_version=order_row_version,
            payment_request_public_id=request_ref,
            merchant_public_id=merchant_ref,
            gateway_merchant_id=gateway_merchant_id,
            service_credential_reference=credential_ref,
            location_public_id=location_ref,
            catalog_version=catalog_version,
        )

        settlements = XafPayV2Service.repository.settlement_count_for_attempt(
            session,
            tenant_id=tenant_id,
            attempt_public_id=attempt_id,
        )
        if attempt.attempt_state == "succeeded":
            if settlements != 1:
                raise RuntimeError("XAFPAY_WND_SETTLEMENT_CARDINALITY_CONFLICT")
            raise RuntimeError("XAFPAY_WND_OBLIGATION_ALREADY_SETTLED")
        if settlements != 0:
            raise RuntimeError("XAFPAY_WND_NON_SUCCESS_SETTLEMENT_CONFLICT")
        if attempt.attempt_state in {"failed", "cancelled", "expired"}:
            raise RuntimeError("XAFPAY_WND_CANONICAL_RETRY_REQUIRES_NEW_AUTHORITY")
        if attempt.attempt_state not in {"pending", "processing", "requires_action"}:
            raise RuntimeError("XAFPAY_WND_CANONICAL_ATTEMPT_STATE_UNSUPPORTED")

        request = WndMerchantCheckoutRequest(
            payment_attempt_public_id=attempt.public_id,
            amount=attempt.attempted_amount,
            currency_code=attempt.currency_code,
            payment_method_code=attempt.payment_method_code,
            payment_rail_code=attempt.payment_rail_code,
            tenant_id=tenant_id,
            wnd_merchant_public_id=merchant_ref,
            wnd_order_public_id=order_ref,
            wnd_location_public_id=location_ref,
            wnd_order_revision=order_row_version,
            wnd_catalog_version=catalog_version,
        )
        # CheckoutSession creation is presentation evidence, not financial-state
        # authority. Do not write checkout identity into immutable attempt metadata
        # and do not advance the attempt before a signed Gateway Payment event can
        # bind the real pay_ identity. Exact replay is provided by the stable
        # Gateway idempotency key derived from canonical WND order + revision.
        checkout = client.create_checkout(request)

        return {
            "order_ref": str(order_ref),
            "payment_request_ref": str(request_ref),
            "payment_intent_ref": str(intent_id),
            "payment_attempt_ref": str(attempt.public_id),
            "canonical_amount": attempt.attempted_amount,
            "currency": attempt.currency_code,
            "gateway_merchant_id": str(gateway_merchant_id),
            "checkout_session_id": checkout.checkout_session_id,
            "checkout_token": checkout.public_token,
            "presentation_state": checkout.presentation_state,
            "checkout_status": checkout.status,
            "payment_status": "PAYMENT_PENDING",
            "paid": False,
            "can_fulfill": False,
        }

    @classmethod
    def canonical_status(
        cls,
        session,
        *,
        tenant_id: int,
        organization_unit_id: int,
        merchant_public_id: UUID,
        gateway_merchant_id: str,
        service_credential_reference: str,
        order_public_id: UUID,
        order_row_version: int,
        location_public_id: UUID,
        catalog_version: int,
        payment_request_public_id: UUID,
    ) -> dict:
        order_ref = UUID(str(order_public_id))
        merchant_ref = UUID(str(merchant_public_id))
        location_ref = UUID(str(location_public_id))
        request_ref = UUID(str(payment_request_public_id))
        if order_row_version <= 0 or catalog_version <= 0:
            raise RuntimeError("XAFPAY_WND_CANONICAL_SOURCE_VERSION_INVALID")
        attempt_id = cls._canonical_attempt_id(request_ref)
        intent_id = cls._canonical_intent_id(request_ref)
        attempt = XafPayV2Service.repository.attempt_authority(
            session, attempt_id, lock=False
        )
        if attempt is None:
            return {
                "order_ref": str(order_ref),
                "payment_request_ref": str(request_ref),
                "payment_intent_ref": str(intent_id),
                "payment_attempt_ref": str(attempt_id),
                "gateway_payment_id": None,
                "checkout_session_id": None,
                "checkout_status": None,
                "attempt_state": "not_started",
                "confirmed_settlements": 0,
                "canonical_amount": None,
                "currency": "XAF",
                "payment_status": "PAYMENT_NOT_STARTED",
                "paid": False,
                "can_fulfill": False,
            }
        if (
            attempt.tenant_id != tenant_id
            or attempt.organization_unit_id != organization_unit_id
            or attempt.payment_intent_public_id != intent_id
        ):
            raise RuntimeError("XAFPAY_WND_CANONICAL_ATTEMPT_SCOPE_MISMATCH")
        cls._validate_canonical_metadata(
            attempt,
            order_public_id=order_ref,
            order_row_version=order_row_version,
            payment_request_public_id=request_ref,
            merchant_public_id=merchant_ref,
            gateway_merchant_id=gateway_merchant_id,
            service_credential_reference=service_credential_reference,
            location_public_id=location_ref,
            catalog_version=catalog_version,
        )
        settlements = XafPayV2Service.repository.settlement_count_for_attempt(
            session,
            tenant_id=tenant_id,
            attempt_public_id=attempt.public_id,
        )
        state = str(attempt.attempt_state)
        if state == "succeeded":
            if settlements != 1:
                raise RuntimeError("XAFPAY_WND_SETTLEMENT_CARDINALITY_CONFLICT")
            payment_status = "PAYMENT_CONFIRMED"
            paid = True
        else:
            if settlements != 0:
                raise RuntimeError("XAFPAY_WND_NON_SUCCESS_SETTLEMENT_CONFLICT")
            if state in {"pending", "processing", "requires_action"}:
                payment_status = "PAYMENT_PENDING"
            elif state in {"failed", "cancelled", "expired"}:
                payment_status = "PAYMENT_NOT_CONFIRMED"
            else:
                raise RuntimeError("XAFPAY_WND_CANONICAL_ATTEMPT_STATE_UNSUPPORTED")
            paid = False
        metadata = dict(attempt.metadata or {})
        return {
            "order_ref": str(order_ref),
            "payment_request_ref": str(request_ref),
            "payment_intent_ref": str(intent_id),
            "payment_attempt_ref": str(attempt.public_id),
            "gateway_payment_id": attempt.external_attempt_reference,
            "checkout_session_id": metadata.get("checkout_session_id"),
            "checkout_status": metadata.get("checkout_status"),
            "attempt_state": state,
            "confirmed_settlements": settlements,
            "canonical_amount": attempt.attempted_amount,
            "currency": attempt.currency_code,
            "payment_status": payment_status,
            "paid": paid,
            "can_fulfill": paid,
        }
