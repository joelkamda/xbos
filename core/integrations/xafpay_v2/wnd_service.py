"""WND adapter into the single neutral XBOS XafPay V2 orchestration path."""
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
from .contract import XafPayV2CreatePaymentRequest
from .service import XafPayV2Service


def _stable(kind: str, tenant_id: int, order_id: int, client_reference: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"xbos:xv15:wnd:{kind}:{tenant_id}:{order_id}:{client_reference}")


class WndXafPayV2Service:
    """Creates unresolved external-payment intent only; success arrives by signed event."""

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
        client_reference: str,
        client: XafPayV2Client,
    ) -> dict:
        selected_amount = Decimal(amount)
        if selected_amount <= 0 or selected_amount != selected_amount.to_integral_value():
            raise ValueError("XV15_WND_AMOUNT_MUST_BE_POSITIVE_WHOLE_XAF")
        rail_code = {"mtn": "MTN_MOMO", "orange": "ORANGE_MONEY"}.get(rail.lower())
        if rail_code is None:
            raise ValueError("XV15_WND_RAIL_UNSUPPORTED")
        now = datetime.now(timezone.utc)
        intent_id = _stable("intent", tenant_id, order_id, client_reference)
        tender_id = _stable("tender", tenant_id, order_id, client_reference)
        attempt_id = _stable("attempt", tenant_id, order_id, client_reference)
        correlation_id = _stable("correlation", tenant_id, order_id, client_reference)
        request = XafPayV2CreatePaymentRequest(
            payment_attempt_public_id=attempt_id,
            amount=selected_amount,
            currency_code="XAF",
            payment_method_code="MOBILE_MONEY",
            payment_rail_code=rail_code,
            channel="xbos",
        )
        existing = XafPayV2Service.repository.attempt_authority(session, attempt_id, lock=False)
        if existing is not None:
            if (
                existing.tenant_id != tenant_id
                or existing.attempted_amount != selected_amount
                or existing.payment_rail_code.upper() != rail_code
                or existing.metadata.get("order_id") != order_id
                or existing.metadata.get("sale_id") != sale_id
            ):
                raise RuntimeError("XV15_XAFPAY_ATTEMPT_IDEMPOTENCY_CONFLICT")
            if not existing.external_attempt_reference:
                raise RuntimeError("XV15_XAFPAY_ATTEMPT_BINDING_INCOMPLETE")
            checkout = client.create_checkout(request, existing.external_attempt_reference)
            return {
                "order_id": order_id,
                "sale_id": sale_id,
                "intent_public_id": str(existing.payment_intent_public_id),
                "tender_public_id": str(existing.payment_tender_public_id),
                "attempt_public_id": str(existing.public_id),
                "gateway_payment_id": existing.external_attempt_reference,
                "checkout_session_id": checkout["checkout_session_id"],
                "checkout_token": checkout["public_token"],
                "status": "SUCCEEDED" if existing.attempt_state == "succeeded" else "PENDING",
            }
        prior = XafPayV2Service.repository.latest_attempt_for_order(session, tenant_id, order_id)
        if prior is not None:
            if prior.attempt_state not in {"failed", "cancelled", "expired"}:
                raise RuntimeError("XV15_XAFPAY_UNRESOLVED_ATTEMPT_BLOCKS_RETRY")
            attempt = TransactionalPaymentAttemptEngine.create(
                session,
                CreatePaymentAttemptCommand(
                    public_id=attempt_id,
                    tenant_id=tenant_id,
                    organization_unit_id=organization_unit_id,
                    payment_intent_public_id=prior.payment_intent_public_id,
                    payment_tender_public_id=prior.payment_tender_public_id,
                    attempted_amount=selected_amount,
                    currency_code="XAF",
                    payment_method_code="MOBILE_MONEY",
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
                    idempotency_scope="wnd.xafpay_v2.attempt",
                    idempotency_key=client_reference,
                    metadata={"order_id": order_id, "sale_id": sale_id, "authority": "GATEWAY_EXECUTION"},
                ),
            ).payment_attempt
            response = XafPayV2Service.initiate_attempt(
                session, attempt_public_id=attempt.public_id, client=client, channel="xbos"
            )
            checkout = client.create_checkout(request, response.payment_id)
            return {
                "order_id": order_id, "sale_id": sale_id,
                "intent_public_id": str(prior.payment_intent_public_id),
                "tender_public_id": str(prior.payment_tender_public_id),
                "attempt_public_id": str(attempt.public_id),
                "gateway_payment_id": response.payment_id,
                "checkout_session_id": checkout["checkout_session_id"],
                "checkout_token": checkout["public_token"], "status": "PENDING",
            }
        intent = TransactionalPaymentIntentEngine.create_intent(
            session,
            CreatePaymentIntentCommand(
                public_id=intent_id,
                tenant_id=tenant_id,
                organization_unit_id=organization_unit_id,
                requested_amount=selected_amount,
                currency_code="XAF",
                payment_method_policy={"allowed_methods": ["mobile_money"], "allow_mixed_tender": False, "max_tenders": 1},
                occurred_at=now,
                business_date=now.date(),
                calendar_policy_version=1,
                correlation_id=correlation_id,
                actor_service="wnd.xafpay_v2",
                source_component="wnd.payment",
                source_record_id=f"order:{order_id}",
                idempotency_scope="wnd.xafpay_v2.intent",
                idempotency_key=client_reference,
                metadata={"order_id": order_id, "sale_id": sale_id, "authority": "XBOS"},
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
                tender_amount=selected_amount,
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
                idempotency_key=client_reference,
                metadata={"order_id": order_id, "rail": rail_code, "authority": "XBOS"},
            ),
        ).tender
        attempt = TransactionalPaymentAttemptEngine.create(
            session,
            CreatePaymentAttemptCommand(
                public_id=attempt_id,
                tenant_id=tenant_id,
                organization_unit_id=organization_unit_id,
                payment_intent_public_id=intent.public_id,
                payment_tender_public_id=tender.public_id,
                attempted_amount=selected_amount,
                currency_code="XAF",
                payment_method_code="MOBILE_MONEY",
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
                idempotency_key=client_reference,
                metadata={"order_id": order_id, "sale_id": sale_id, "authority": "GATEWAY_EXECUTION"},
            ),
        ).payment_attempt
        response = XafPayV2Service.initiate_attempt(
            session, attempt_public_id=attempt.public_id, client=client, channel="xbos"
        )
        checkout = client.create_checkout(request, response.payment_id)
        if XafPayV2Service.repository.settlement_count_for_attempt(
            session, tenant_id=tenant_id, attempt_public_id=attempt.public_id
        ) != 0:
            raise RuntimeError("XV15_XAFPAY_SELECTION_CREATED_SETTLEMENT")
        return {
            "order_id": order_id,
            "sale_id": sale_id,
            "intent_public_id": str(intent.public_id),
            "tender_public_id": str(tender.public_id),
            "attempt_public_id": str(attempt.public_id),
            "gateway_payment_id": response.payment_id,
            "checkout_session_id": checkout["checkout_session_id"],
            "checkout_token": checkout["public_token"],
            "status": "PENDING",
        }
