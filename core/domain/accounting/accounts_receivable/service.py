from __future__ import annotations

import hashlib
from decimal import Decimal
from datetime import datetime, timezone
from typing import Any, Dict

from sqlalchemy.orm import Session

from core.shared.idempotency import (
    check_idempotency_key,
    record_idempotency_key,
)

from core.domain.accounting.accounts_receivable.models import (
    AccountsReceivable,
    AccountsReceivableRepayment,
)
from core.domain.accounting.accounts_receivable.repository import (
    AccountsReceivableRepository,
)
from core.domain.accounting.emitter import FinancialEventEmitter
from core.domain.payments.models import (
    PaymentAttemptStatus,
    PaymentIntentStatus,
)
from core.domain.payments.repository import (
    PaymentAttemptRepository,
    PaymentIntentRepository,
)
from core.domain.payments.service import PaymentService
from core.domain.sales.models import SaleStatus
from core.domain.sales.repository import SaleRepository
from core.domain.orders.repository import OrderRepository
from core.domain.inventory.service import InventoryService


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


def _clean_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _idempotency_reference_id(existing: Any) -> int | None:
    if not existing:
        return None

    if hasattr(existing, "reference_id"):
        value = existing.reference_id
    elif isinstance(existing, dict):
        value = existing.get("reference_id")
    else:
        try:
            value = existing["reference_id"]
        except Exception:
            value = None

    try:
        return int(value) if value is not None else None
    except Exception:
        return None


def _repayment_idempotency_key(
    *,
    tenant_id: int,
    branch_id: int,
    ar_id: int,
    client_reference: str,
) -> str:
    """Create a compact deterministic key safe for the shared key table."""

    raw = f"{tenant_id}|{branch_id}|{ar_id}|{client_reference.strip()}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    return f"ar:{tenant_id}:{branch_id}:{ar_id}:{digest}"


def _payment_summary(
    *,
    existing_summary: Any,
    intent,
    attempts,
    total_paid: Decimal,
    balance_due: Decimal,
    tendered_total: Decimal,
    last_repayment_id: int,
) -> Dict[str, Any]:
    method_totals: Dict[str, Decimal] = {}

    for attempt in attempts:
        status_value = str(getattr(attempt.status, "value", attempt.status) or "").lower()
        if status_value not in {"succeeded", "success", "paid", "completed"}:
            continue

        method = str(attempt.method or "unknown").lower()
        method_totals[method] = method_totals.get(method, Decimal("0")) + _d(attempt.amount)

    base = dict(existing_summary) if isinstance(existing_summary, dict) else {}

    return {
        **base,
        "payment_intent_id": int(intent.id),
        "total_paid": float(total_paid),
        "balance_due": float(balance_due),
        "unpaid_amount": float(balance_due),
        "tendered_total": float(tendered_total),
        "methods": [
            {"method": method, "amount": float(amount)}
            for method, amount in sorted(method_totals.items())
        ],
        "last_repayment_id": int(last_repayment_id),
    }


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

        clean_customer_name = _clean_text(customer_name)
        clean_customer_phone = _clean_text(customer_phone)

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
            existing.customer_name = clean_customer_name or existing.customer_name
            existing.customer_phone = clean_customer_phone or existing.customer_phone
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
            customer_name=clean_customer_name,
            customer_phone=clean_customer_phone,
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
    def update_identity(
        db: Session,
        *,
        tenant_id: int,
        branch_id: int,
        ar_id: int,
        customer_name: Any,
        customer_phone: Any = None,
    ) -> AccountsReceivable:
        """
        Update debtor identity only.

        Financial invariants are deliberately outside the writable surface:
        original_amount, paid_amount, balance_due, status, sale/order links,
        and payment_intent_id are never touched here.
        """

        ar = AccountsReceivableRepository.get_by_id_for_update(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            ar_id=ar_id,
        )

        if not ar:
            raise ValueError("A/R account not found")

        clean_name = _clean_text(customer_name)
        if not clean_name:
            raise ValueError("Debtor name is required")

        ar.customer_name = clean_name
        ar.customer_phone = _clean_text(customer_phone)
        ar.updated_at = _utc_now()

        db.add(ar)
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
        client_reference: str | None = None,
        created_by_user_id: int | None = None,
    ) -> AccountsReceivable:
        """
        Record one A/R repayment and synchronize all payment truth atomically.

        Updated in the same database transaction:
        - accounts_receivable + repayment history
        - payment_attempts + payment_intents
        - sale payment totals / status / payment summary
        - originating order status
        - DEBT_REPAYMENT treasury transfer

        Accounting rule:
        - DEBT_REPAYMENT is the only treasury event emitted here.
        - Do not also emit PAYMENT_RECEIVED, because that would count the
          receiving channel twice in reconciliation.
        """

        # Lock the financial row before reading its balance. This serializes
        # concurrent cashier submissions and prevents over-repayment races.
        ar = AccountsReceivableRepository.get_by_id_for_update(
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
        clean_client_reference = _clean_text(client_reference)
        clean_reference = _clean_text(reference)
        clean_note = _clean_text(note)

        # Client-supplied idempotency is optional for backward compatibility.
        # The matching frontend patch supplies it for every repayment.
        idempotency_key = None
        if clean_client_reference:
            idempotency_key = _repayment_idempotency_key(
                tenant_id=tenant_id,
                branch_id=branch_id,
                ar_id=ar_id,
                client_reference=clean_client_reference,
            )

            existing = check_idempotency_key(
                db,
                key=idempotency_key,
                scope="accounts_receivable_repayment",
            )

            existing_repayment_id = _idempotency_reference_id(existing)
            if existing_repayment_id:
                existing_repayment = AccountsReceivableRepository.get_repayment_by_id(
                    db,
                    tenant_id=tenant_id,
                    branch_id=branch_id,
                    repayment_id=existing_repayment_id,
                )

                if not existing_repayment or existing_repayment.ar_id != ar.id:
                    raise ValueError(
                        "Broken A/R repayment idempotency reference"
                    )

                # Safe retry: return the already-updated account without
                # creating a second repayment, attempt, or treasury movement.
                return ar

        # Resolve the authoritative PaymentIntent linked to this receivable.
        intent = None

        if ar.payment_intent_id:
            try:
                intent = PaymentIntentRepository.get_by_id(
                    db,
                    tenant_id=tenant_id,
                    intent_id=int(ar.payment_intent_id),
                )
            except (TypeError, ValueError):
                intent = None

        if not intent and ar.sale_id:
            intent = PaymentIntentRepository.get_by_payable(
                db,
                tenant_id=tenant_id,
                payable_type="sale",
                payable_id=int(ar.sale_id),
            )

        if not intent:
            raise ValueError(
                "A/R account is not linked to a valid PaymentIntent"
            )

        if int(getattr(intent, "branch_id", branch_id)) != int(branch_id):
            raise ValueError("PaymentIntent branch mismatch")

        original_amount = _d(intent.amount)
        if original_amount <= 0:
            original_amount = _d(ar.original_amount)

        if original_amount <= 0:
            raise ValueError("A/R account has no valid original amount")

        attempts_paid_before = min(
            original_amount,
            _d(
                PaymentAttemptRepository.sum_succeeded_for_intent(
                    db,
                    intent_id=intent.id,
                )
            ),
        )

        previous_paid = max(
            min(original_amount, _d(ar.paid_amount)),
            min(original_amount, _d(intent.total_paid)),
            attempts_paid_before,
        )
        previous_balance = max(Decimal("0"), original_amount - previous_paid)

        if previous_balance <= 0:
            raise ValueError("A/R account is already settled")

        if amount_d > previous_balance:
            raise ValueError(
                f"Repayment amount exceeds balance due ({previous_balance})"
            )

        now = _utc_now()

        repayment = AccountsReceivableRepayment(
            tenant_id=tenant_id,
            branch_id=branch_id,
            ar_id=ar.id,
            amount=amount_d,
            payment_method=payment_channel,
            reference=clean_reference,
            note=clean_note,
            created_by_user_id=created_by_user_id,
            created_at=now,
        )

        AccountsReceivableRepository.create_repayment(db, repayment)
        db.flush()

        # One successful PaymentAttempt makes the repayment visible in the
        # Payments module and in the canonical sale receipt.
        attempt = PaymentService.create_attempt(
            db,
            intent=intent,
            amount=amount_d,
            method=payment_channel,
            provider=payment_channel,
            settlement_mode="ar_repayment",
            client_reference=f"ar-repayment:{repayment.id}",
            provider_reference=clean_reference,
            status=PaymentAttemptStatus.succeeded,
            meta={
                "source": "accounts_receivable_repayment",
                "ar_id": ar.id,
                "repayment_id": repayment.id,
                "order_id": ar.order_id,
                "sale_id": ar.sale_id,
                "payment_intent_id": intent.id,
                "payment_method": payment_channel,
                "reference": clean_reference,
                "note": clean_note,
                "client_reference": clean_client_reference,
                "created_by_user_id": created_by_user_id,
            },
        )
        attempt.cashier_id = created_by_user_id
        attempt.completed_at = now
        db.add(attempt)
        db.flush()

        attempts_paid_after = _d(
            PaymentAttemptRepository.sum_succeeded_for_intent(
                db,
                intent_id=intent.id,
            )
        )

        next_paid = min(
            original_amount,
            max(previous_paid + amount_d, attempts_paid_after),
        )
        next_balance = max(Decimal("0"), original_amount - next_paid)

        # -----------------------------------------------------
        # A/R aggregate
        # -----------------------------------------------------
        ar.original_amount = original_amount
        ar.paid_amount = next_paid
        ar.balance_due = next_balance

        if next_balance <= 0:
            ar.status = "settled"
            ar.settled_at = now
        else:
            ar.status = "partial" if next_paid > 0 else "open"
            ar.settled_at = None

        ar.updated_at = now
        db.add(ar)

        # -----------------------------------------------------
        # PaymentIntent aggregate
        # -----------------------------------------------------
        PaymentIntentRepository.set_totals(
            intent=intent,
            total_paid=next_paid,
            balance_due=next_balance,
        )

        PaymentIntentRepository.set_status(
            intent=intent,
            status=(
                PaymentIntentStatus.succeeded
                if next_balance <= 0
                else PaymentIntentStatus.processing
            ),
        )

        intent_meta = dict(intent.meta or {})
        raw_repayment_meta = intent_meta.get("ar_repayments")
        repayment_meta = (
            list(raw_repayment_meta)
            if isinstance(raw_repayment_meta, list)
            else []
        )

        if not any(
            int(item.get("repayment_id") or 0) == int(repayment.id)
            for item in repayment_meta
            if isinstance(item, dict)
        ):
            repayment_meta.append(
                {
                    "repayment_id": repayment.id,
                    "ar_id": ar.id,
                    "amount": float(amount_d),
                    "payment_method": payment_channel,
                    "reference": clean_reference,
                    "note": clean_note,
                    "created_by_user_id": created_by_user_id,
                    "created_at": now.isoformat(),
                }
            )

        cumulative_tendered = max(attempts_paid_after, next_paid)

        intent_meta.update(
            {
                "ar_repayments": repayment_meta,
                "last_ar_repayment_id": repayment.id,
                "last_ar_repayment_amount": float(amount_d),
                "tendered_total": float(cumulative_tendered),
                "total_tendered": float(cumulative_tendered),
                "total_paid": float(next_paid),
                "paid_total": float(next_paid),
                "balance_due": float(next_balance),
                "unpaid_total": float(next_balance),
                "current_unpaid_amount": float(next_balance),
            }
        )
        intent.meta = intent_meta
        db.add(intent)

        # -----------------------------------------------------
        # Sale aggregate and receipt-facing payment summary
        # -----------------------------------------------------
        sale_id = ar.sale_id
        if not sale_id and str(intent.payable_type or "").lower() == "sale":
            sale_id = intent.payable_id

        sale = None
        if sale_id:
            sale = SaleRepository.get_by_id(
                db,
                tenant_id=tenant_id,
                sale_id=int(sale_id),
            )

        if not sale:
            raise ValueError("A/R account is not linked to a valid Sale")

        if int(sale.branch_id) != int(branch_id):
            raise ValueError("Sale branch mismatch")

        attempts = PaymentAttemptRepository.list_for_intent(
            db,
            intent_id=intent.id,
        )

        ar.payment_intent_id = str(intent.id)
        ar.sale_id = sale.id
        if not ar.order_id and getattr(sale, "order_id", None):
            ar.order_id = sale.order_id

        sale.tendered_total = cumulative_tendered
        sale.unpaid_amount = next_balance
        sale.payment_summary = _payment_summary(
            existing_summary=sale.payment_summary,
            intent=intent,
            attempts=attempts,
            total_paid=next_paid,
            balance_due=next_balance,
            tendered_total=cumulative_tendered,
            last_repayment_id=repayment.id,
        )

        if next_balance <= 0:
            SaleRepository.update_status(
                sale=sale,
                new_status=SaleStatus.paid,
            )
            if not sale.paid_at:
                SaleRepository.set_paid_at(sale=sale, paid_at=now)

            InventoryService.finalize_sale_inventory(db, sale=sale)
        else:
            SaleRepository.update_status(
                sale=sale,
                new_status=SaleStatus.pending_payment,
            )
            sale.paid_at = None

        db.add(sale)

        # -----------------------------------------------------
        # Originating order
        # -----------------------------------------------------
        if ar.order_id:
            order = OrderRepository.get_by_id(db, int(ar.order_id))

            if not order:
                raise ValueError("Originating order not found")

            if (
                int(order.tenant_id) != int(tenant_id)
                or int(order.branch_id) != int(branch_id)
            ):
                raise ValueError("Originating order tenant/branch mismatch")

            if next_balance <= 0:
                OrderRepository.mark_paid(order)
            else:
                OrderRepository.mark_receivable(order)

            db.add(order)

        # -----------------------------------------------------
        # Treasury transfer - deliberately no PAYMENT_RECEIVED
        # -----------------------------------------------------
        FinancialEventEmitter.debt_repaid(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            repayment_id=repayment.id,
            amount=amount_d,
            currency=(intent.currency or "XAF"),
            channel=payment_channel,
            occurred_at=now,
            meta={
                "source": "accounts_receivable_repayment",
                "event_reason": "customer_debt_repaid",
                "movement_direction": "ar_repayment_transfer",
                "source_channel": "ar",
                "target_channel": payment_channel,
                "ar_id": ar.id,
                "order_id": ar.order_id,
                "sale_id": sale.id,
                "payment_intent_id": intent.id,
                "payment_attempt_id": attempt.id,
                "repayment_id": repayment.id,
                "payment_method": payment_channel,
                "reference": clean_reference,
                "note": clean_note,
                "client_reference": clean_client_reference,
                "created_by_user_id": created_by_user_id,
                "original_amount": float(original_amount),
                "repayment_amount": float(amount_d),
                "previous_paid_amount": float(previous_paid),
                "previous_balance_due": float(previous_balance),
                "paid_amount_after": float(next_paid),
                "balance_due_after": float(next_balance),
                "status_after": ar.status,
            },
        )

        if idempotency_key:
            record_idempotency_key(
                db,
                key=idempotency_key,
                scope="accounts_receivable_repayment",
                reference_id=repayment.id,
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