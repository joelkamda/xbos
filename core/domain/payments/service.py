from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from core.domain.payments.models import (
    PaymentIntent,
    PaymentAttempt,
    PaymentIntentStatus,
    PaymentAttemptStatus,
    PaymentMethod,
    PaymentProvider,
    SettlementMode,
)
from core.domain.payments.repository import (
    PaymentIntentRepository,
    PaymentAttemptRepository,
)
from core.domain.sales.models import SaleStatus
from core.domain.sales.repository import SaleRepository
from core.shared.idempotency import (
    check_idempotency_key,
    record_idempotency_key,
)


class PaymentService:
    """
    Tier-1 Settlement Authority for XBOS.

    Architecture:
        Sale → PaymentIntent → PaymentAttempt(s)

    Guarantees:
        - Split-safe
        - Idempotent
        - Intent becomes PAID only when total_paid >= amount
        - Sale becomes PAID only when intent becomes PAID
        - Inventory deduction happens only when intent becomes PAID
    """

    # =====================================================
    # INTENT CREATION
    # =====================================================

    @staticmethod
    def create_intent_for_sale(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        sale_id: int,
        amount: Decimal,
        created_by_user_id: int,
        client_reference: str,
    ) -> PaymentIntent:

        existing = check_idempotency_key(
            db,
            key=client_reference,
            scope="payment_intent",
        )
        if existing:
            intent = PaymentIntentRepository.get_by_id(
                db,
                tenant_id=tenant_id,
                intent_id=existing.reference_id,
            )
            if intent:
                return intent

        intent = PaymentIntent(
            tenant_id=tenant_id,
            branch_id=branch_id,
            payable_type="sale",
            payable_id=sale_id,
            currency="XAF",
            amount=amount,
            status=PaymentIntentStatus.pending,
            total_paid=Decimal("0"),
            balance_due=amount,
            created_by_user_id=created_by_user_id,
            channel="pos",
        )

        PaymentIntentRepository.create(db, intent=intent)

        record_idempotency_key(
            db,
            key=client_reference,
            scope="payment_intent",
            reference_id=intent.id,
        )

        return intent

    # =====================================================
    # ATTEMPT INITIALIZATION
    # =====================================================

    @staticmethod
    def init_attempt(
        db: Session,
        *,
        tenant_id: int,
        intent_id: int,
        method: PaymentMethod,
        provider: Optional[PaymentProvider],
        amount: Decimal,
        cashier_id: Optional[int],
        client_reference: str,
    ) -> PaymentAttempt:

        existing = check_idempotency_key(
            db,
            key=client_reference,
            scope="payment_attempt",
        )
        if existing:
            attempt = PaymentAttemptRepository.get_by_id(
                db,
                tenant_id=tenant_id,
                attempt_id=existing.reference_id,
            )
            if attempt:
                return attempt

        # Determine settlement mode
        if method in (PaymentMethod.cash, PaymentMethod.mtn, PaymentMethod.orange):
            settlement_mode = SettlementMode.instant
        else:
            settlement_mode = SettlementMode.async_gateway

        attempt = PaymentAttempt(
            payment_intent_id=intent_id,
            method=method,
            provider=provider,
            settlement_mode=settlement_mode,
            amount=amount,
            status=PaymentAttemptStatus.pending,
            client_reference=client_reference,
            cashier_id=cashier_id,
        )

        PaymentAttemptRepository.create(db, attempt=attempt)

        record_idempotency_key(
            db,
            key=client_reference,
            scope="payment_attempt",
            reference_id=attempt.id,
        )

        # Instant settlement → immediately mark success
        if settlement_mode == SettlementMode.instant:
            PaymentService.mark_attempt_success(
                db=db,
                tenant_id=tenant_id,
                attempt_id=attempt.id,
            )

        return attempt

    # =====================================================
    # SUCCESS HANDLER
    # =====================================================

    @staticmethod
    def mark_attempt_success(
        db: Session,
        *,
        tenant_id: int,
        attempt_id: int,
        gateway_reference: Optional[str] = None,
        callback_reference: Optional[str] = None,
    ) -> PaymentAttempt:

        # Webhook idempotency
        if callback_reference:
            existing = check_idempotency_key(
                db,
                key=callback_reference,
                scope="payment_callback",
            )
            if existing:
                attempt = PaymentAttemptRepository.get_by_id(
                    db,
                    tenant_id=tenant_id,
                    attempt_id=existing.reference_id,
                )
                if attempt:
                    return attempt

        attempt = PaymentAttemptRepository.get_by_id(
            db,
            tenant_id=tenant_id,
            attempt_id=attempt_id,
        )
        if not attempt:
            raise ValueError("PaymentAttempt not found")

        if attempt.status == PaymentAttemptStatus.paid:
            return attempt

        if attempt.status in (
            PaymentAttemptStatus.failed,
            PaymentAttemptStatus.cancelled,
        ):
            raise ValueError("Cannot mark failed/cancelled attempt as paid")

        PaymentAttemptRepository.set_status(
            attempt=attempt,
            status=PaymentAttemptStatus.paid,
        )

        PaymentAttemptRepository.set_completed_at(
            attempt=attempt,
            completed_at=datetime.utcnow(),
        )

        if gateway_reference:
            PaymentAttemptRepository.set_gateway_reference(
                attempt=attempt,
                reference=gateway_reference,
            )

        # Recompute intent
        PaymentService._recompute_intent(
            db=db,
            tenant_id=tenant_id,
            intent_id=attempt.payment_intent_id,
        )

        if callback_reference:
            record_idempotency_key(
                db,
                key=callback_reference,
                scope="payment_callback",
                reference_id=attempt.id,
            )

        return attempt

    # =====================================================
    # FAILURE HANDLER
    # =====================================================

    @staticmethod
    def mark_attempt_failed(
        db: Session,
        *,
        tenant_id: int,
        attempt_id: int,
        gateway_reference: Optional[str] = None,
        callback_reference: Optional[str] = None,
    ) -> PaymentAttempt:

        attempt = PaymentAttemptRepository.get_by_id(
            db,
            tenant_id=tenant_id,
            attempt_id=attempt_id,
        )
        if not attempt:
            raise ValueError("PaymentAttempt not found")

        if attempt.status == PaymentAttemptStatus.failed:
            return attempt

        PaymentAttemptRepository.set_status(
            attempt=attempt,
            status=PaymentAttemptStatus.failed,
        )

        PaymentAttemptRepository.set_completed_at(
            attempt=attempt,
            completed_at=datetime.utcnow(),
        )

        return attempt

    # =====================================================
    # INTERNAL INTENT RECOMPUTE
    # =====================================================

    @staticmethod
    def _recompute_intent(
        db: Session,
        *,
        tenant_id: int,
        intent_id: int,
    ) -> None:

        intent = PaymentIntentRepository.get_by_id(
            db,
            tenant_id=tenant_id,
            intent_id=intent_id,
        )
        if not intent:
            return

        total_paid = PaymentAttemptRepository.sum_paid_for_intent(
            db,
            tenant_id=tenant_id,
            intent_id=intent_id,
        )

        balance_due = Decimal(intent.amount) - total_paid
        if balance_due < 0:
            balance_due = Decimal("0")

        PaymentIntentRepository.update_aggregates(
            intent=intent,
            total_paid=total_paid,
            balance_due=balance_due,
        )

        # Determine status
        if total_paid == 0:
            new_status = PaymentIntentStatus.pending
        elif total_paid < intent.amount:
            new_status = PaymentIntentStatus.partially_paid
        else:
            new_status = PaymentIntentStatus.paid

        PaymentIntentRepository.set_status(
            intent=intent,
            status=new_status,
        )

        # If fully paid → mark Sale paid
        if new_status == PaymentIntentStatus.paid and intent.payable_type == "sale":
            sale = SaleRepository.get_by_id(
                db,
                tenant_id=tenant_id,
                sale_id=intent.payable_id,
            )
            if sale and sale.status != SaleStatus.paid:
                SaleRepository.update_status(
                    sale=sale,
                    new_status=SaleStatus.paid,
                )
                SaleRepository.set_paid_at(
                    sale=sale,
                    paid_at=datetime.utcnow(),
                )

                # TODO: Trigger inventory deduction here