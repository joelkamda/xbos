from decimal import Decimal
from typing import Optional, Dict, Any
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from core.domain.accounting.repository import TreasuryRepository


# ============================================================
# CONSTANTS
# ============================================================

SETTLEMENT_CHANNELS = {"cash", "mtn", "orange", "xafpay", "bank"}


# ============================================================
# HELPERS
# ============================================================

def _utc_now() -> datetime:
    """
    Canonical ledger timestamp.

    The database stores treasury log timestamps as timestamptz.
    Therefore this emitter writes timezone-aware UTC instants.

    Display conversion to Africa/Douala belongs in the API serializer/UI,
    not inside the stored ledger value.
    """

    return datetime.now(timezone.utc)


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

    if ch in SETTLEMENT_CHANNELS:
        return ch

    return ch


def _safe_settlement_channel(channel: Optional[str], *, fallback: str = "cash") -> str:
    ch = str(channel or fallback).strip().lower()

    if ch not in SETTLEMENT_CHANNELS:
        raise ValueError(
            "Invalid settlement channel. "
            "Allowed values are: cash, mtn, orange, xafpay, bank"
        )

    return ch


def _json_safe(value: Any) -> Any:
    """
    Make ledger metadata safe for JSON columns.

    This prevents accidental JSON serialization failures when a service passes
    Decimal or datetime values inside meta.
    """

    if isinstance(value, Decimal):
        return float(value)

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc).isoformat()
        return value.astimezone(timezone.utc).isoformat()

    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}

    if isinstance(value, list):
        return [_json_safe(v) for v in value]

    if isinstance(value, tuple):
        return [_json_safe(v) for v in value]

    return value


def _clean_meta(meta: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not meta:
        return {}

    if isinstance(meta, dict):
        return _json_safe(dict(meta))

    return {}


def _normalize_occurred_at(value: Optional[datetime]) -> datetime:
    """
    Normalize event occurrence time for timestamptz storage.

    Rules:
    - Missing value: use current UTC-aware instant.
    - Aware datetime: convert to UTC.
    - Naive datetime: treat as UTC wall-clock and attach UTC.

    Why:
    PostgreSQL timestamptz is correct for ledger timestamps, but naive values
    are dangerous if the DB/session timezone is not UTC. This helper prevents
    the old +7 hour future-time problem.
    """

    if value is None:
        return _utc_now()

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


class FinancialEventEmitter:
    """
    The ONLY component allowed to create TreasuryLog records.

    Guarantees:
    • Idempotent ledger writes
    • Decimal safety
    • UTC-aware event timestamps
    • Canonical financial event taxonomy

    Design:
    - Sales/revenue recognition emits commercial truth.
    - Payment collection emits cashflow truth.
    - Manual income/expense/cash-movement helpers support accounting modals.
    - CASH_MOVE uses direction="credit" because treasury_logs.direction only
      allows credit/debit. The movement meaning is carried by event_type and meta.
    - A/R repayment is a transfer: A/R mv out, payment channel mv in.
    - Future A/P return/change settlement should mirror this idea in reverse.
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
            occurred_at=_normalize_occurred_at(occurred_at),
            meta=_clean_meta(meta),
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
                **_clean_meta(meta),
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
                **_clean_meta(meta),
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
        - A/R and A/P are not allowed as ordinary manual movement channels.
        - direction remains "credit" to satisfy DB constraint.
        - reconciliation uses event_type + source/target metadata.
        """

        amount = _d(amount)

        if amount <= 0:
            return None

        if not client_reference:
            raise ValueError("client_reference is required")

        source = _safe_settlement_channel(source_channel)
        target = _safe_settlement_channel(target_channel)

        if source == target:
            raise ValueError("source_channel and target_channel cannot be the same")

        movement_meta = {
            **_clean_meta(meta),
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
        occurred_at: Optional[datetime] = None,
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
            occurred_at=occurred_at,
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
        occurred_at: Optional[datetime] = None,
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
            occurred_at=occurred_at,
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
        occurred_at: Optional[datetime] = None,
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
            occurred_at=occurred_at,
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
        occurred_at: Optional[datetime] = None,
    ):
        safe_channel = _safe_settlement_channel(channel)

        return FinancialEventEmitter.emit(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            idempotency_key=f"pay_attempt:{attempt_id}",
            direction="credit",
            event_type="PAYMENT_RECEIVED",
            amount=amount,
            currency=currency,
            channel=safe_channel,
            reference_type="payment_attempt",
            reference_id=attempt_id,
            occurred_at=occurred_at,
            meta={
                **_clean_meta(meta),
                "source_channel": safe_channel,
                "target_channel": safe_channel,
                "movement_direction": "payment_collection",
            },
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
        occurred_at: Optional[datetime] = None,
    ):
        if _d(amount) <= 0:
            return None

        safe_channel = _safe_settlement_channel(channel)

        return FinancialEventEmitter.emit(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            idempotency_key=f"change_returned:intent:{payment_intent_id}",
            direction="debit",
            event_type="CHANGE_RETURNED",
            amount=amount,
            currency=currency,
            channel=safe_channel,
            reference_type="payment_intent",
            reference_id=payment_intent_id,
            occurred_at=occurred_at,
            meta={
                **_clean_meta(meta),
                "source_channel": safe_channel,
                "target_channel": "customer",
                "movement_direction": "change_returned",
            },
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
        occurred_at: Optional[datetime] = None,
    ):
        """
        Creates A/R.

        Accounting meaning:
        - New debt is unrealized income parked in A/R.
        - Reconciliation should map:
            A/R income += amount
        """

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
            channel="ar",
            reference_type="sale",
            reference_id=sale_id,
            occurred_at=occurred_at,
            meta={
                **_clean_meta(meta),
                "source": "accounts_receivable",
                "target_channel": "ar",
                "movement_direction": "ar_created",
            },
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
        occurred_at: Optional[datetime] = None,
    ):
        """
        Repays A/R.

        Accounting meaning:
        - This is NOT new income.
        - This is NOT expense.
        - This is a transfer:
            A/R account      movement out
            Payment channel  movement in

        Reconciliation should map:
            rows["ar"]["cashOut"] += amount
            rows[channel]["cashIn"] += amount
        """

        amount_d = _d(amount)

        if amount_d <= 0:
            return None

        target_channel = _safe_settlement_channel(channel)

        movement_meta = {
            **_clean_meta(meta),
            "source": "accounts_receivable_repayment",
            "source_channel": "ar",
            "target_channel": target_channel,
            "movement_direction": "ar_repayment_transfer",
        }

        return FinancialEventEmitter.emit(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            idempotency_key=f"debt_repaid:{repayment_id}",
            direction="credit",
            event_type="DEBT_REPAYMENT",
            amount=amount_d,
            currency=currency,
            channel=target_channel,
            reference_type="debt_repayment",
            reference_id=repayment_id,
            occurred_at=occurred_at,
            meta=movement_meta,
        )

    # =========================================================
    # STORE CREDIT / ACCOUNTS PAYABLE-LIKE LIABILITY
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
        occurred_at: Optional[datetime] = None,
    ):
        """
        Creates A/P-like customer liability / store credit.

        Current meaning:
        - Customer change due is parked in A/P-like liability.
        - It is not income.
        - It is not an expense at creation.
        - It represents value owed to customer.

        Future A/P reconciliation model:
        - Creation should increase A/P.
        - Actual cash is already retained in the payment channel at settlement.
        - Returning change should reduce A/P and create cashOut from the channel.
        - If store credit is consumed by goods later, it should reduce A/P and
          may become sale settlement value, depending on the final design.
        """

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
            channel="ap",
            reference_type="sale",
            reference_id=sale_id,
            occurred_at=occurred_at,
            meta={
                **_clean_meta(meta),
                "source": "accounts_payable_like_store_credit",
                "target_channel": "ap",
                "movement_direction": "ap_created",
            },
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
        occurred_at: Optional[datetime] = None,
    ):
        amount_d = _d(amount)

        if amount_d <= 0:
            return None

        safe_channel = _safe_settlement_channel(channel)

        return FinancialEventEmitter.emit(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            idempotency_key=f"refund:{refund_id}",
            direction="debit",
            event_type="REFUND_PAID",
            amount=amount_d,
            currency=currency,
            channel=safe_channel,
            reference_type="refund",
            reference_id=refund_id,
            occurred_at=occurred_at,
            meta={
                **_clean_meta(meta),
                "source_channel": safe_channel,
                "target_channel": "customer",
                "movement_direction": "refund_paid",
            },
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
        occurred_at: Optional[datetime] = None,
    ):
        amount_d = _d(amount)

        if amount_d <= 0:
            return None

        source = _safe_settlement_channel(source_channel)
        target = _safe_settlement_channel(target_channel)

        if source == target:
            raise ValueError("source_channel and target_channel cannot be the same")

        movement_meta = {
            **_clean_meta(meta),
            "source_channel": source,
            "target_channel": target,
            "movement_direction": "transfer",
        }

        return FinancialEventEmitter.emit(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            idempotency_key=f"cash_move:{move_id}",
            direction="credit",
            event_type="CASH_MOVE",
            amount=amount_d,
            currency=currency,
            channel=target,
            reference_type="cash_move",
            reference_id=move_id,
            occurred_at=occurred_at,
            meta=movement_meta,
        )