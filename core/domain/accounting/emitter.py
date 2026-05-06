from decimal import Decimal
from typing import Optional, Dict, Any
from datetime import datetime

from sqlalchemy.orm import Session

from core.domain.accounting.repository import TreasuryRepository


def _d(v) -> Decimal:
    try:
        if v is None:
            return Decimal("0")
        return Decimal(str(v))
    except Exception:
        return Decimal("0")


def _safe_channel(channel: Optional[str]) -> Optional[str]:
    if not channel:
        return None

    ch = str(channel).strip().lower()

    if ch in {"cash", "mtn", "orange", "xafpay", "bank"}:
        return ch

    return ch


class FinancialEventEmitter:
    """
    The ONLY component allowed to create TreasuryLog records.

    Guarantees:
    • Idempotent ledger writes
    • Decimal safety
    • Consistent timestamps
    • Canonical financial event taxonomy

    Design:
    - Sales/revenue recognition emits commercial truth.
    - Payment collection emits cashflow truth.
    - Manual income/expense/cash-movement helpers support accounting modals.
    - CASH_MOVE uses direction="credit" because treasury_logs.direction only
      allows credit/debit. The movement meaning is carried by event_type and meta.
    - All helpers ultimately call emit().
    """

    # =========================================================
    # CORE EMITTER
    # =========================================================

    @staticmethod
    def emit(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        idempotency_key: str,
        direction: str,
        event_type: str,
        amount,
        currency: str = "XAF",
        channel: Optional[str] = None,
        reference_type: Optional[str] = None,
        reference_id: Optional[int] = None,
        taxonomy_node_id: Optional[int] = None,
        occurred_at: Optional[datetime] = None,
        meta: Optional[Dict[str, Any]] = None,
    ):

        amount = _d(amount)

        if amount == Decimal("0"):
            return None

        safe_direction = str(direction or "").strip().lower()
        if safe_direction not in {"credit", "debit"}:
            raise ValueError("TreasuryLog direction must be 'credit' or 'debit'")

        existing = TreasuryRepository.get_by_idempotency(
            db,
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
        )

        if existing:
            return existing

        return TreasuryRepository.record(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            idempotency_key=idempotency_key,
            direction=safe_direction,
            event_type=event_type,
            amount=amount,
            currency=(currency or "XAF").upper(),
            channel=_safe_channel(channel),
            reference_type=reference_type,
            reference_id=reference_id,
            taxonomy_node_id=taxonomy_node_id,
            occurred_at=occurred_at or datetime.utcnow(),
            meta=meta or {},
        )

    # =========================================================
    # MANUAL ACCOUNTING MODAL EVENTS
    # =========================================================

    @staticmethod
    def manual_income(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        client_reference: str,
        amount,
        channel: str,
        taxonomy_node_id: int,
        currency: str = "XAF",
        event_type: str = "OTHER_INCOME",
        occurred_at: Optional[datetime] = None,
        meta: Optional[Dict[str, Any]] = None,
    ):
        """
        Manual non-sales income.

        Used by:
        - New Income modal

        Expected taxonomy context:
        FINANCE → Revenue → category → subcategory

        Reconciliation effect:
        selected channel expected balance increases.
        """

        amount = _d(amount)

        if amount <= 0:
            return None

        if not client_reference:
            raise ValueError("client_reference is required")

        if not taxonomy_node_id:
            raise ValueError("taxonomy_node_id is required for manual income")

        allowed_events = {
            "OTHER_INCOME",
            "SERVICE_REVENUE",
            "TIP_REVENUE",
        }

        safe_event_type = event_type if event_type in allowed_events else "OTHER_INCOME"

        return FinancialEventEmitter.emit(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            idempotency_key=f"manual_income:{client_reference}",
            direction="credit",
            event_type=safe_event_type,
            amount=amount,
            currency=currency,
            channel=channel,
            reference_type="manual_income",
            reference_id=0,
            taxonomy_node_id=taxonomy_node_id,
            occurred_at=occurred_at,
            meta={
                **(meta or {}),
                "client_reference": client_reference,
                "source": "manual_income_modal",
            },
        )

    @staticmethod
    def expense_posted(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        client_reference: str,
        amount,
        channel: str,
        taxonomy_node_id: int,
        currency: str = "XAF",
        occurred_at: Optional[datetime] = None,
        meta: Optional[Dict[str, Any]] = None,
    ):
        """
        Manual operating expense.

        Used by:
        - New Expense modal

        Expected taxonomy context:
        FINANCE → Expenses → category → subcategory

        Reconciliation effect:
        selected channel expected balance decreases.
        """

        amount = _d(amount)

        if amount <= 0:
            return None

        if not client_reference:
            raise ValueError("client_reference is required")

        if not taxonomy_node_id:
            raise ValueError("taxonomy_node_id is required for expense")

        return FinancialEventEmitter.emit(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            idempotency_key=f"expense:{client_reference}",
            direction="debit",
            event_type="EXPENSE_POSTED",
            amount=amount,
            currency=currency,
            channel=channel,
            reference_type="expense",
            reference_id=0,
            taxonomy_node_id=taxonomy_node_id,
            occurred_at=occurred_at,
            meta={
                **(meta or {}),
                "client_reference": client_reference,
                "source": "expense_modal",
            },
        )

    @staticmethod
    def cash_move_manual(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        client_reference: str,
        amount,
        source_channel: str,
        target_channel: str,
        currency: str = "XAF",
        occurred_at: Optional[datetime] = None,
        meta: Optional[Dict[str, Any]] = None,
    ):
        """
        Manual movement between settlement channels.

        Used by:
        - New Cash Movement modal

        Important:
        - This is not income.
        - This is not expense.
        - A/R and A/P are not allowed as ordinary movement channels.
        - direction remains "credit" to satisfy DB constraint.
        - reconciliation uses event_type + source/target metadata.
        """

        amount = _d(amount)

        if amount <= 0:
            return None

        if not client_reference:
            raise ValueError("client_reference is required")

        source = _safe_channel(source_channel)
        target = _safe_channel(target_channel)

        allowed = {"cash", "mtn", "orange", "xafpay", "bank"}

        if source not in allowed:
            raise ValueError("Invalid source_channel for cash movement")

        if target not in allowed:
            raise ValueError("Invalid target_channel for cash movement")

        if source == target:
            raise ValueError("source_channel and target_channel cannot be the same")

        movement_meta = {
            **(meta or {}),
            "client_reference": client_reference,
            "source": "cash_movement_modal",
            "source_channel": source,
            "target_channel": target,
            "movement_direction": "transfer",
        }

        return FinancialEventEmitter.emit(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            idempotency_key=f"cash_move:{client_reference}",
            direction="credit",
            event_type="CASH_MOVE",
            amount=amount,
            currency=currency,
            channel=target,
            reference_type="cash_move",
            reference_id=0,
            taxonomy_node_id=None,
            occurred_at=occurred_at,
            meta=movement_meta,
        )

    # =========================================================
    # SALES REVENUE RECOGNITION (NON-CASHFLOW)
    # =========================================================

    @staticmethod
    def sale_revenue_gross(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        sale_id: int,
        amount,
        currency="XAF",
        meta=None,
    ):

        return FinancialEventEmitter.emit(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            idempotency_key=f"sale_revenue:{sale_id}",
            direction="credit",
            event_type="SALE_REVENUE_GROSS",
            amount=amount,
            currency=currency,
            reference_type="sale",
            reference_id=sale_id,
            meta=meta,
        )

    @staticmethod
    def sale_discount(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        sale_id: int,
        amount,
        currency="XAF",
        meta=None,
    ):

        if _d(amount) <= 0:
            return None

        return FinancialEventEmitter.emit(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            idempotency_key=f"sale_discount:{sale_id}",
            direction="debit",
            event_type="DISCOUNT_APPLIED",
            amount=amount,
            currency=currency,
            reference_type="sale",
            reference_id=sale_id,
            meta=meta,
        )

    @staticmethod
    def sale_complimentary(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        sale_id: int,
        amount,
        currency="XAF",
        meta=None,
    ):

        if _d(amount) <= 0:
            return None

        return FinancialEventEmitter.emit(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            idempotency_key=f"sale_comp:{sale_id}",
            direction="debit",
            event_type="COMPLIMENTARY_APPLIED",
            amount=amount,
            currency=currency,
            reference_type="sale",
            reference_id=sale_id,
            meta=meta,
        )

    # =========================================================
    # PAYMENT COLLECTION (CASHFLOW)
    # =========================================================

    @staticmethod
    def payment_received(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        attempt_id: int,
        amount,
        currency="XAF",
        channel=None,
        meta=None,
    ):

        return FinancialEventEmitter.emit(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            idempotency_key=f"pay_attempt:{attempt_id}",
            direction="credit",
            event_type="PAYMENT_RECEIVED",
            amount=amount,
            currency=currency,
            channel=channel,
            reference_type="payment_attempt",
            reference_id=attempt_id,
            meta=meta,
        )

    # =========================================================
    # CHANGE RETURNED (CASHFLOW OUT)
    # =========================================================

    @staticmethod
    def change_returned(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        payment_intent_id: int,
        amount,
        currency="XAF",
        channel="cash",
        meta=None,
    ):

        if _d(amount) <= 0:
            return None

        return FinancialEventEmitter.emit(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            idempotency_key=f"change_returned:intent:{payment_intent_id}",
            direction="debit",
            event_type="CHANGE_RETURNED",
            amount=amount,
            currency=currency,
            channel=channel or "cash",
            reference_type="payment_intent",
            reference_id=payment_intent_id,
            meta=meta,
        )

    # =========================================================
    # DEBT / ACCOUNTS RECEIVABLE
    # =========================================================

    @staticmethod
    def debt_created(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        sale_id: int,
        amount,
        currency="XAF",
        meta=None,
    ):

        if _d(amount) <= 0:
            return None

        return FinancialEventEmitter.emit(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            idempotency_key=f"debt_created:{sale_id}",
            direction="debit",
            event_type="DEBT_CREATED",
            amount=amount,
            currency=currency,
            reference_type="sale",
            reference_id=sale_id,
            meta=meta,
        )

    @staticmethod
    def debt_repaid(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        repayment_id: int,
        amount,
        currency="XAF",
        channel=None,
        meta=None,
    ):

        return FinancialEventEmitter.emit(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            idempotency_key=f"debt_repaid:{repayment_id}",
            direction="credit",
            event_type="DEBT_REPAYMENT",
            amount=amount,
            currency=currency,
            channel=channel,
            reference_type="debt_repayment",
            reference_id=repayment_id,
            meta=meta,
        )

    # =========================================================
    # STORE CREDIT (LIABILITY)
    # =========================================================

    @staticmethod
    def store_credit_created(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        sale_id: int,
        amount,
        currency="XAF",
        meta=None,
    ):

        if _d(amount) <= 0:
            return None

        return FinancialEventEmitter.emit(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            idempotency_key=f"store_credit:{sale_id}",
            direction="debit",
            event_type="STORE_CREDIT_CREATED",
            amount=amount,
            currency=currency,
            reference_type="sale",
            reference_id=sale_id,
            meta=meta,
        )

    # =========================================================
    # REFUNDS
    # =========================================================

    @staticmethod
    def refund_paid(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        refund_id: int,
        amount,
        currency="XAF",
        channel=None,
        meta=None,
    ):

        return FinancialEventEmitter.emit(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            idempotency_key=f"refund:{refund_id}",
            direction="debit",
            event_type="REFUND_PAID",
            amount=amount,
            currency=currency,
            channel=channel,
            reference_type="refund",
            reference_id=refund_id,
            meta=meta,
        )

    # =========================================================
    # CASH MOVES (SAFE TRANSFER BETWEEN CHANNELS)
    # =========================================================

    @staticmethod
    def cash_move(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        move_id: int,
        amount,
        source_channel: str,
        target_channel: str,
        currency="XAF",
        meta=None,
    ):

        meta = meta or {}

        source = _safe_channel(source_channel)
        target = _safe_channel(target_channel)

        meta.update(
            {
                "source_channel": source,
                "target_channel": target,
                "movement_direction": "transfer",
            }
        )

        return FinancialEventEmitter.emit(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            idempotency_key=f"cash_move:{move_id}",
            direction="credit",
            event_type="CASH_MOVE",
            amount=amount,
            currency=currency,
            channel=target,
            reference_type="cash_move",
            reference_id=move_id,
            meta=meta,
        )