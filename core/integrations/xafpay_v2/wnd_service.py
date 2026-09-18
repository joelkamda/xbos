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
from .contract import XafPayV2CheckoutRequest, XafPayV2IntegrationError
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
