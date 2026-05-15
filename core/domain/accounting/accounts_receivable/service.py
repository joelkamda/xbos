from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone
from typing import Any, Dict

from sqlalchemy.orm import Session

from core.domain.accounting.accounts_receivable.models import (
    AccountsReceivable,
    AccountsReceivableRepayment,
)
from core.domain.accounting.accounts_receivable.repository import (
    AccountsReceivableRepository,
)
from core.domain.accounting.emitter import FinancialEventEmitter


# ============================================================
# CONSTANTS
# ============================================================

SETTLEMENT_CHANNELS = {"cash", "mtn", "orange", "xafpay", "bank"}


# ============================================================
# HELPERS
# ============================================================

def _utc_now() -> datetime:
    """
    Canonical A/R service timestamp.

    A/R timestamps may be operational records, but repayment events also emit
    treasury ledger records. Using a UTC-aware instant here prevents naive UTC
    from being misread by timestamptz ledger paths.
    """

    return datetime.now(timezone.utc)


def _d(value: Any) -> Decimal:
    try:
        if value is None or value == "":
            return Decimal("0")
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def _safe_payment_channel(value: Any) -> str:
    channel = str(value or "cash").strip().lower()

    if channel not in SETTLEMENT_CHANNELS:
        raise ValueError(
            "Invalid repayment payment_method. "
            "Allowed values are: cash, mtn, orange, xafpay, bank"
        )

    return channel


def _status_from_amounts(*, paid_amount: Decimal, balance_due: Decimal) -> str:
    if balance_due <= 0:
        return "settled"

    if paid_amount > 0:
        return "partial"

    return "open"


def _iso(value: Any) -> str | None:
    if not value:
        return None

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc).isoformat()
        return value.astimezone(timezone.utc).isoformat()

    return value.isoformat() if hasattr(value, "isoformat") else None


# ============================================================
# SERVICE
# ============================================================

class AccountsReceivableService:

    @staticmethod
    def create_or_update_from_settlement(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        order_id: int | None,
        sale_id: int | None,
        payment_intent_id: str | None,
        original_amount: Any,
        paid_amount: Any,
        balance_due: Any,
        customer_name: str | None = None,
        customer_phone: str | None = None,
        note: str | None = None,
        created_by_user_id: int | None = None,
    ) -> AccountsReceivable | None:
        original_d = _d(original_amount)
        paid_d = _d(paid_amount)
        balance_d = _d(balance_due)

        if balance_d <= 0:
            return None

        existing = None

        if order_id:
            existing = AccountsReceivableRepository.get_by_order_id(
                db,
                tenant_id=tenant_id,
                branch_id=branch_id,
                order_id=int(order_id),
            )

        if not existing and sale_id:
            existing = AccountsReceivableRepository.get_by_sale_id(
                db,
                tenant_id=tenant_id,
                branch_id=branch_id,
                sale_id=int(sale_id),
            )

        status = _status_from_amounts(
            paid_amount=paid_d,
            balance_due=balance_d,
        )

        now = _utc_now()

        if existing:
            existing.sale_id = sale_id or existing.sale_id
            existing.payment_intent_id = (
                payment_intent_id or existing.payment_intent_id
            )
            existing.original_amount = original_d
            existing.paid_amount = paid_d
            existing.balance_due = balance_d
            existing.status = status
            existing.customer_name = customer_name or existing.customer_name
            existing.customer_phone = customer_phone or existing.customer_phone
            existing.note = note or existing.note
            existing.updated_at = now

            db.add(existing)
            db.flush()

            return existing

        ar = AccountsReceivable(
            tenant_id=tenant_id,
            branch_id=branch_id,
            order_id=order_id,
            sale_id=sale_id,
            payment_intent_id=payment_intent_id,
            customer_name=customer_name,
            customer_phone=customer_phone,
            note=note,
            original_amount=original_d,
            paid_amount=paid_d,
            balance_due=balance_d,
            status=status,
            created_by_user_id=created_by_user_id,
            created_at=now,
            updated_at=now,
        )

        AccountsReceivableRepository.create(db, ar)
        db.flush()

        return ar

    @staticmethod
    def list_open(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        limit: int = 200,
        offset: int = 0,
    ):
        return AccountsReceivableRepository.list_open(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            limit=limit,
            offset=offset,
        )

    @staticmethod
    def record_repayment(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        ar_id: int,
        amount: Any,
        payment_method: str,
        reference: str | None = None,
        note: str | None = None,
        created_by_user_id: int | None = None,
    ) -> AccountsReceivable:
        """
        Record customer repayment against Accounts Receivable.

        Accounting meaning:
        - This is NOT new income.
        - This is NOT an expense.
        - This is a transfer:
            A/R account      movement out
            Payment channel  movement in

        Ledger event:
        - Emits DEBT_REPAYMENT through FinancialEventEmitter.
        - Reconciliation should map:
            rows["ar"]["cashOut"] += amount
            rows[payment_channel]["cashIn"] += amount

        Future A/P symmetry:
        - A/P return/refund should use the reverse pattern:
            A/P movement out and channel cashOut, not income/expense.
        """

        ar = AccountsReceivableRepository.get_by_id(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            ar_id=ar_id,
        )

        if not ar:
            raise ValueError("A/R account not found")

        amount_d = _d(amount)

        if amount_d <= 0:
            raise ValueError("Repayment amount must be greater than zero")

        payment_channel = _safe_payment_channel(payment_method)

        previous_paid = _d(ar.paid_amount)
        previous_balance = _d(ar.balance_due)

        next_paid = previous_paid + amount_d
        next_balance = _d(ar.original_amount) - next_paid

        now = _utc_now()

        repayment = AccountsReceivableRepayment(
            tenant_id=tenant_id,
            branch_id=branch_id,
            ar_id=ar.id,
            amount=amount_d,
            payment_method=payment_channel,
            reference=reference,
            note=note,
            created_by_user_id=created_by_user_id,
            created_at=now,
        )

        AccountsReceivableRepository.create_repayment(db, repayment)

        # Flush before ledger emission so repayment.id exists for:
        # - idempotency key: debt_repaid:{repayment.id}
        # - reference_type/reference_id on treasury_logs
        db.flush()

        ar.paid_amount = next_paid
        ar.balance_due = next_balance

        if ar.balance_due <= 0:
            ar.status = "settled"
            ar.settled_at = now
        elif ar.paid_amount > 0:
            ar.status = "partial"
            ar.settled_at = None
        else:
            ar.status = "open"
            ar.settled_at = None

        ar.updated_at = now

        db.add(ar)
        db.flush()

        FinancialEventEmitter.debt_repaid(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            repayment_id=repayment.id,
            amount=amount_d,
            currency="XAF",
            channel=payment_channel,
            occurred_at=now,
            meta={
                "source": "accounts_receivable_repayment",
                "event_reason": "customer_debt_repaid",
                "movement_direction": "ar_repayment_transfer",

                # Transfer semantics for reconciliation/investigation.
                "source_channel": "ar",
                "target_channel": payment_channel,

                # A/R identity.
                "ar_id": ar.id,
                "order_id": ar.order_id,
                "sale_id": ar.sale_id,
                "payment_intent_id": ar.payment_intent_id,

                # Repayment identity.
                "repayment_id": repayment.id,
                "payment_method": payment_channel,
                "reference": reference,
                "note": note,
                "created_by_user_id": created_by_user_id,

                # Audit snapshot.
                "original_amount": float(_d(ar.original_amount)),
                "repayment_amount": float(amount_d),
                "previous_paid_amount": float(previous_paid),
                "previous_balance_due": float(previous_balance),
                "paid_amount_after": float(next_paid),
                "balance_due_after": float(next_balance),
                "status_after": ar.status,
            },
        )

        db.flush()

        return ar

    @staticmethod
    def serialize(ar: AccountsReceivable) -> Dict[str, Any]:
        return {
            "id": ar.id,
            "tenant_id": ar.tenant_id,
            "branch_id": ar.branch_id,
            "order_id": ar.order_id,
            "sale_id": ar.sale_id,
            "payment_intent_id": ar.payment_intent_id,
            "customer_name": ar.customer_name,
            "customer_phone": ar.customer_phone,
            "note": ar.note,
            "original_amount": float(ar.original_amount or 0),
            "paid_amount": float(ar.paid_amount or 0),
            "balance_due": float(ar.balance_due or 0),
            "status": ar.status,
            "created_by_user_id": ar.created_by_user_id,
            "created_at": _iso(ar.created_at),
            "updated_at": _iso(ar.updated_at),
            "settled_at": _iso(ar.settled_at),
        }