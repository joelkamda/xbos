from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from core.domain.accounting.models import TreasuryLog
from core.domain.payments.models import PaymentIntent
import uuid
from decimal import Decimal
from typing import Any, Dict, List

import httpx
from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from settings import settings

from core.domain.payments.service import PaymentService
from core.domain.payments.repository import (
    PaymentIntentRepository,
    PaymentAttemptRepository,
)
from core.domain.sales.repository import SaleRepository
from core.domain.sales.service import SaleService
from core.domain.orders.repository import OrderRepository
from core.domain.accounting.accounts_receivable.service import (
    AccountsReceivableService,
)
from core.domain.accounting.accounts_receivable.repository import (
    AccountsReceivableRepository,
)
from core.domain.accounting.accounting_controller import AccountingController


def _d(v: Any) -> Decimal:
    try:
        if v is None or v == "":
            return Decimal("0")
        return Decimal(str(v))
    except Exception:
        return Decimal("0")


def _status_ui(value: Any) -> str:
    raw = getattr(value, "value", value)
    raw = str(raw or "").lower()

    if raw in {"succeeded", "success", "completed", "complete", "paid"}:
        return "COMPLETED"

    if raw in {"failed", "failure", "cancelled", "canceled", "error"}:
        return "FAILED"

    return "PENDING"


def _clean_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _extract_customer_name(receipt_meta: Dict[str, Any]) -> str | None:
    customer = receipt_meta.get("customer")

    if isinstance(customer, dict):
        return _clean_text(
            customer.get("name")
            or customer.get("full_name")
            or customer.get("customer_name")
        )

    return _clean_text(
        receipt_meta.get("customer_name")
        or receipt_meta.get("client_name")
        or customer
    )


def _extract_customer_phone(receipt_meta: Dict[str, Any]) -> str | None:
    customer = receipt_meta.get("customer")

    if isinstance(customer, dict):
        return _clean_text(
            customer.get("phone")
            or customer.get("telephone")
            or customer.get("mobile")
            or customer.get("customer_phone")
        )

    return _clean_text(
        receipt_meta.get("customer_phone")
        or receipt_meta.get("phone")
        or receipt_meta.get("telephone")
    )


def _extract_customer_id(receipt_meta: Dict[str, Any]) -> int | None:
    customer = receipt_meta.get("customer")
    value = None
    if isinstance(customer, dict):
        value = customer.get("id") or customer.get("customer_id")
    if value is None:
        value = receipt_meta.get("customer_id")
    try:
        return int(value) if value is not None and str(value).strip() else None
    except Exception:
        return None


def _extract_note(receipt_meta: Dict[str, Any], fallback_note: Any = None) -> str | None:
    return _clean_text(
        receipt_meta.get("notes")
        or receipt_meta.get("note")
        or receipt_meta.get("unpaid_note")
        or fallback_note
    )


class PaymentsController:
    # =====================================================
    # INTERNAL HELPERS
    # =====================================================

    def _get_ctx(self, request: Request) -> Dict[str, Any]:
        ctx = getattr(request.state, "user", None)

        if not ctx:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing authentication context",
            )

        return ctx

    def _resolve_sale_from_order(
        self,
        *,
        db: Session,
        tenant_id: int,
        branch_id: int,
        user_id: int,
        order_id: int,
    ):
        sale = SaleRepository.get_by_order_id(
            db,
            tenant_id=tenant_id,
            order_id=order_id,
        )

        if sale:
            return sale

        order = OrderRepository.get_by_id(db, order_id)

        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found",
            )

        if order.tenant_id != tenant_id or order.branch_id != branch_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Order does not belong to current tenant/branch",
            )

        return SaleService.create_sale_from_order(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            cashier_id=user_id,
            order=order,
        )

    def _apply_order_settlement_status_and_ar(
        self,
        *,
        db: Session,
        tenant_id: int,
        branch_id: int,
        user_id: int,
        order_id: int,
        sale,
        intent,
        receipt_meta: Dict[str, Any],
        note: Any = None,
    ):
        """
        Finalizes order destination after settlement.

        Full payment:
        - order.status = paid
        - no active A/R row

        Unpaid / partial:
        - create or update accounts_receivable
        - order.status = receivable
        - PendingOrdersScreen clears because it only shows pending_payment
        """

        order = OrderRepository.get_by_id(db, int(order_id))

        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found during settlement finalization",
            )

        balance_due_d = _d(getattr(intent, "balance_due", 0))
        total_paid_d = _d(getattr(intent, "total_paid", 0))
        original_amount_d = _d(getattr(intent, "amount", None) or getattr(sale, "total", 0))

        if balance_due_d <= 0:
            OrderRepository.mark_paid(order)
            db.add(order)
            return None

        # AUX1 debtor-intake guard. This runs only after PaymentService has
        # resolved the authoritative final balance, so discounts, prior
        # attempts, and partial settlement math cannot produce a false guard.
        existing_ar = (
            AccountsReceivableRepository.get_by_order_id(
                db,
                tenant_id=tenant_id,
                branch_id=branch_id,
                order_id=int(order_id),
            )
            or AccountsReceivableRepository.get_by_sale_id(
                db,
                tenant_id=tenant_id,
                branch_id=branch_id,
                sale_id=int(getattr(sale, "id", 0) or 0),
            )
        )

        customer_name = _extract_customer_name(receipt_meta)
        customer_phone = _extract_customer_phone(receipt_meta)
        customer_id = _extract_customer_id(receipt_meta)

        # Existing historical unnamed receivables remain operable and can be
        # identified later from Accounting > Accounts. Every NEW A/R account
        # must identify the debtor before the settlement is committed.
        if not existing_ar and not customer_name:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Debtor name is required before leaving a sale balance "
                    "on Accounts Receivable"
                ),
            )

        ar = AccountsReceivableService.create_or_update_from_settlement(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            order_id=int(order_id),
            sale_id=getattr(sale, "id", None),
            payment_intent_id=str(getattr(intent, "id", "") or ""),
            original_amount=original_amount_d,
            paid_amount=total_paid_d,
            balance_due=balance_due_d,
            customer_name=customer_name,
            customer_phone=customer_phone,
            customer_id=customer_id,
            note=_extract_note(receipt_meta, note),
            created_by_user_id=user_id,
        )

        OrderRepository.mark_receivable(order)
        db.add(order)

        return ar

    # =====================================================
    # LIST PAYMENTS (UI DASHBOARD)
    # =====================================================

    async def list_payments(self, request: Request, db: Session):
        ctx = self._get_ctx(request)

        tenant_id = ctx["tenant_id"]
        branch_id = ctx["branch_id"]

        intents = PaymentIntentRepository.list_recent(
            db=db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            limit=50,
        )

        results = []

        for intent in intents:
            meta = intent.meta or {}

            attempts = PaymentAttemptRepository.list_for_intent(
                db=db,
                intent_id=intent.id,
            )

            last_attempt = attempts[-1] if attempts else None
            successful_attempts = [
                a
                for a in attempts
                if str(getattr(a.status, "value", a.status)).lower()
                in {"succeeded", "success", "completed", "complete", "paid"}
            ]

            methods = {
                str(a.method).lower()
                for a in successful_attempts
                if getattr(a, "method", None)
            }

            if len(methods) > 1:
                method = "split"
            elif last_attempt and last_attempt.method:
                method = str(last_attempt.method).lower()
            else:
                method = intent.channel

            provider = last_attempt.provider if last_attempt else None

            enriched_meta = {
                **meta,
                "total_paid": float(intent.total_paid or 0),
                "balance_due": float(intent.balance_due or 0),
                "amount": float(intent.amount or 0),
            }

            results.append(
                {
                    "id": str(intent.id),
                    "sale_id": intent.payable_id
                    if intent.payable_type == "sale"
                    else meta.get("sale_id"),
                    "payable_type": intent.payable_type,
                    "payable_id": intent.payable_id,
                    "customer_name": (
                        meta.get("customer_name")
                        or (meta.get("customer") or {}).get("name")
                    ),
                    "phone": (
                        meta.get("phone")
                        or (meta.get("customer") or {}).get("phone")
                    ),
                    "amount": float(intent.amount or 0),
                    "total_paid": float(intent.total_paid or 0),
                    "balance_due": float(intent.balance_due or 0),
                    "method": method,
                    "provider": provider,
                    "status": _status_ui(intent.status),
                    "created_at": intent.created_at.isoformat()
                    if intent.created_at
                    else None,
                    "meta": enriched_meta,
                }
            )

        return results

    # =====================================================
    # SINGLE PAYMENT (RIGHT PANEL)
    # =====================================================

    async def get_payment(self, request: Request, payment_id: str, db: Session):
        ctx = self._get_ctx(request)

        tenant_id = ctx["tenant_id"]
        branch_id = ctx["branch_id"]

        intent = PaymentIntentRepository.get_by_id(
            db=db,
            tenant_id=tenant_id,
            intent_id=payment_id,
        )

        if not intent or getattr(intent, "branch_id", None) != branch_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Payment not found",
            )

        attempts = PaymentAttemptRepository.list_for_intent(
            db=db,
            intent_id=intent.id,
        )

        return {
            "id": str(intent.id),
            "sale_id": intent.payable_id
            if intent.payable_type == "sale"
            else None,
            "payable_type": intent.payable_type,
            "payable_id": intent.payable_id,
            "amount": float(intent.amount or 0),
            "currency": intent.currency,
            "method": intent.channel,
            "status": _status_ui(intent.status),
            "total_paid": float(intent.total_paid or 0),
            "balance_due": float(intent.balance_due or 0),
            "created_at": intent.created_at.isoformat()
            if intent.created_at
            else None,
            "meta": {
                **(intent.meta or {}),
                "total_paid": float(intent.total_paid or 0),
                "balance_due": float(intent.balance_due or 0),
            },
            "attempts": [
                {
                    "id": str(a.id),
                    "provider": a.provider,
                    "method": a.method,
                    "settlement_mode": a.settlement_mode,
                    "amount": float(a.amount or 0),
                    "status": _status_ui(a.status),
                    "created_at": a.created_at.isoformat()
                    if a.created_at
                    else None,
                    "meta": a.meta or {},
                }
                for a in attempts
            ],
        }

    # =====================================================
    # PAYMENTS ACTIVITY READ MODEL
    # =====================================================

    async def list_activity(
        self,
        request: Request,
        db: Session,
        limit: int = 100,
    ):
        # Read-only projection:
        # - posted movement comes from TreasuryLog
        # - unresolved work comes from PaymentIntent
        # - no ledger, PaymentIntent, or financial event is created here.
        ctx = self._get_ctx(request)
        tenant_id = ctx["tenant_id"]
        branch_id = ctx["branch_id"]

        safe_limit = max(10, min(int(limit or 100), 250))

        posted_event_types = (
            "PAYMENT_RECEIVED",
            "DEBT_REPAYMENT",
            "OTHER_INCOME",
            "SERVICE_REVENUE",
            "EXPENSE_POSTED",
            "REFUND_PAID",
            "CASH_MOVE",
        )

        recent_events = (
            db.query(TreasuryLog)
            .filter(
                TreasuryLog.tenant_id == tenant_id,
                TreasuryLog.branch_id == branch_id,
                TreasuryLog.event_type.in_(posted_event_types),
            )
            .order_by(TreasuryLog.occurred_at.desc(), TreasuryLog.id.desc())
            .limit(safe_limit * 3)
            .all()
        )

        unresolved_statuses = ("pending", "processing", "failed", "cancelled")
        recent_intents = (
            db.query(PaymentIntent)
            .filter(
                PaymentIntent.tenant_id == tenant_id,
                PaymentIntent.branch_id == branch_id,
                PaymentIntent.status.in_(unresolved_statuses),
            )
            .order_by(PaymentIntent.created_at.desc(), PaymentIntent.id.desc())
            .limit(safe_limit)
            .all()
        )

        def _clean(value):
            text = str(value or "").strip()
            return text or None

        def _event_reference(log, meta):
            event_type = str(log.event_type or "").upper()

            if event_type == "PAYMENT_RECEIVED":
                sale_id = (
                    meta.get("sale_id")
                    or meta.get("payable_id")
                    or (
                        log.reference_id
                        if str(log.reference_type or "").lower() == "sale"
                        else None
                    )
                )
                if sale_id:
                    return f"Sale #{sale_id}"

            if event_type == "DEBT_REPAYMENT":
                sale_id = meta.get("sale_id")
                ar_id = (
                    meta.get("ar_id")
                    or meta.get("accounts_receivable_id")
                    or meta.get("receivable_id")
                )
                if sale_id:
                    return f"Sale #{sale_id}"
                if ar_id:
                    return f"A/R #{ar_id}"

            explicit = (
                meta.get("reference")
                or meta.get("receipt_ref")
                or meta.get("bill_reference")
                or meta.get("client_reference")
            )
            if explicit:
                return str(explicit)

            if log.reference_type and log.reference_id:
                return f"{log.reference_type} #{log.reference_id}"

            return None

        def _event_row(log):
            meta = log.meta or {}
            event_type = str(log.event_type or "").upper()
            amount = float(log.amount or 0)

            labels = {
                "PAYMENT_RECEIVED": "Sale payment",
                "DEBT_REPAYMENT": "A/R payment",
                "OTHER_INCOME": "Income",
                "SERVICE_REVENUE": "Income",
                "EXPENSE_POSTED": "Expense",
                "REFUND_PAID": "Refund",
                "CASH_MOVE": "Transfer",
            }

            if event_type in {
                "PAYMENT_RECEIVED",
                "DEBT_REPAYMENT",
                "OTHER_INCOME",
                "SERVICE_REVENUE",
            }:
                flow = "in"
            elif event_type in {"EXPENSE_POSTED", "REFUND_PAID"}:
                flow = "out"
            else:
                flow = "transfer"

            source_channel = _clean(meta.get("source_channel"))
            target_channel = _clean(meta.get("target_channel"))

            if event_type == "CASH_MOVE" and (source_channel or target_channel):
                channel = f"{source_channel or '?'} → {target_channel or '?'}"
            else:
                channel = _clean(log.channel) or "—"

            detail = (
                meta.get("item_name")
                or meta.get("subcategory_name")
                or meta.get("category_name")
                or meta.get("source_name")
                or meta.get("vendor")
                or meta.get("note")
            )

            return {
                "id": f"event:{log.id}",
                "source": "treasury_event",
                "source_id": log.id,
                "activity_type": labels.get(event_type, event_type.replace("_", " ").title()),
                "event_type": event_type,
                "status": "POSTED",
                "flow": flow,
                "amount": amount,
                "currency": str(log.currency or "XAF"),
                "channel": channel,
                "reference": _event_reference(log, meta),
                "detail": _clean(detail),
                "occurred_at": log.occurred_at.isoformat() if log.occurred_at else None,
                "document_type": {
                    "OTHER_INCOME": "income_receipt",
                    "SERVICE_REVENUE": "income_receipt",
                    "DEBT_REPAYMENT": "payment_receipt",
                    "EXPENSE_POSTED": "payment_voucher",
                    "CASH_MOVE": "transfer_slip",
                }.get(event_type),
                "_sort_at": log.occurred_at or log.created_at,
            }

        def _intent_row(intent):
            meta = intent.meta or {}
            raw_status = str(getattr(intent.status, "value", intent.status) or "").lower()
            balance_due = float(intent.balance_due or 0)
            total_amount = float(intent.amount or 0)
            amount = balance_due if balance_due > 0 else total_amount

            payable_type = str(intent.payable_type or "").strip().lower()
            payable_id = intent.payable_id

            if payable_type == "sale" and payable_id:
                reference = f"Sale #{payable_id}"
            elif payable_type and payable_id:
                reference = f"{payable_type.replace('_', ' ').title()} #{payable_id}"
            else:
                reference = None

            detail = (
                meta.get("customer_name")
                or meta.get("customer")
                or meta.get("description")
                or meta.get("reference")
            )

            return {
                "id": f"intent:{intent.id}",
                "source": "payment_intent",
                "source_id": intent.id,
                "activity_type": (
                    "Outstanding payment"
                    if raw_status in {"pending", "processing"}
                    else "Payment intent"
                ),
                "event_type": "PAYMENT_INTENT",
                "status": raw_status.upper() or "PENDING",
                "flow": "attention",
                "amount": amount,
                "currency": str(intent.currency or "XAF"),
                "channel": _clean(intent.channel) or "—",
                "reference": reference,
                "detail": _clean(detail),
                "occurred_at": intent.created_at.isoformat() if intent.created_at else None,
                "document_type": None,
                "_sort_at": intent.created_at,
            }

        rows = [_event_row(log) for log in recent_events]
        rows.extend(_intent_row(intent) for intent in recent_intents)
        rows.sort(
            key=lambda row: (
                row.get("_sort_at") is not None,
                row.get("_sort_at"),
                row.get("id"),
            ),
            reverse=True,
        )
        rows = rows[:safe_limit]

        for row in rows:
            row.pop("_sort_at", None)

        # Track A / WND authoritative business-day window: 08:00 → 08:00 Douala.
        business_tz = ZoneInfo("Africa/Douala")
        now_local = datetime.now(business_tz)
        window_start = now_local.replace(hour=8, minute=0, second=0, microsecond=0)
        if now_local < window_start:
            window_start = window_start - timedelta(days=1)
        window_end = window_start + timedelta(days=1)

        window_events = (
            db.query(TreasuryLog)
            .filter(
                TreasuryLog.tenant_id == tenant_id,
                TreasuryLog.branch_id == branch_id,
                TreasuryLog.occurred_at >= window_start,
                TreasuryLog.occurred_at < window_end,
                TreasuryLog.event_type.in_(posted_event_types),
            )
            .all()
        )

        received_types = {
            "PAYMENT_RECEIVED",
            "DEBT_REPAYMENT",
            "OTHER_INCOME",
            "SERVICE_REVENUE",
        }
        paid_types = {"EXPENSE_POSTED", "REFUND_PAID"}

        received = sum(
            float(log.amount or 0)
            for log in window_events
            if str(log.event_type or "").upper() in received_types
        )
        paid_out = sum(
            float(log.amount or 0)
            for log in window_events
            if str(log.event_type or "").upper() in paid_types
        )
        transferred = sum(
            float(log.amount or 0)
            for log in window_events
            if str(log.event_type or "").upper() == "CASH_MOVE"
        )

        attention = (
            db.query(PaymentIntent)
            .filter(
                PaymentIntent.tenant_id == tenant_id,
                PaymentIntent.branch_id == branch_id,
                PaymentIntent.status.in_(("pending", "processing", "failed")),
            )
            .count()
        )

        return {
            "window": {
                "label": "Current business day",
                "timezone": "Africa/Douala",
                "start": window_start.isoformat(),
                "end": window_end.isoformat(),
            },
            "summary": {
                "received": received,
                "paid_out": paid_out,
                "transferred": transferred,
                "attention": attention,
            },
            "count": len(rows),
            "items": rows,
        }

    # =====================================================
    # STANDALONE INCOME TAXONOMY
    # =====================================================

    async def standalone_income_taxonomy(
        self,
        request: Request,
        db: Session,
    ):
        """Expose canonical Revenue taxonomy to Payments operators."""
        self._get_ctx(request)
        return AccountingController.taxonomy_tree(
            request=request,
            db=db,
            taxonomy_type="FINANCE",
            domain_name="Revenue",
        )

    # =====================================================
    # STANDALONE EXPENSE TAXONOMY
    # =====================================================

    async def standalone_expense_taxonomy(
        self,
        request: Request,
        db: Session,
    ):
        """Expose canonical Expenses taxonomy to Payments operators."""
        self._get_ctx(request)
        return AccountingController.taxonomy_tree(
            request=request,
            db=db,
            taxonomy_type="FINANCE",
            domain_name="Expenses",
        )

    # =====================================================
    # STANDALONE RECEIVE INCOME
    # =====================================================

    async def standalone_receive_income(
        self,
        request: Request,
        payload: Dict[str, Any],
        db: Session,
    ):
        """Delegate standalone income directly to canonical Accounting truth."""
        self._get_ctx(request)
        return AccountingController.create_manual_income(
            request=request,
            db=db,
            payload=payload,
        )

    # =====================================================
    # STANDALONE PAY EXPENSE
    # =====================================================

    async def standalone_pay_expense(
        self,
        request: Request,
        payload: Dict[str, Any],
        db: Session,
    ):
        """Delegate standalone expense directly to canonical Accounting truth."""
        self._get_ctx(request)
        return AccountingController.create_expense(
            request=request,
            db=db,
            payload=payload,
        )

    # =====================================================
    # STANDALONE TRANSFER
    # =====================================================

    async def standalone_transfer(
        self,
        request: Request,
        payload: Dict[str, Any],
        db: Session,
    ):
        """Delegate standalone transfer directly to canonical cash-movement truth."""
        self._get_ctx(request)
        return AccountingController.create_cash_movement(
            request=request,
            db=db,
            payload=payload,
        )

    # =====================================================
    # POS SETTLEMENT (ORDER-DRIVEN / MANUAL / BALANCE)
    # =====================================================

    async def pos_settle(
        self,
        request: Request,
        payload: Dict[str, Any],
        db: Session,
    ):
        ctx = self._get_ctx(request)

        tenant_id = ctx["tenant_id"]
        branch_id = ctx["branch_id"]
        user_id = ctx["user_id"]

        order_id = payload.get("order_id")
        client_reference = payload.get("client_reference")
        lines: List[Dict[str, Any]] = payload.get("lines") or []

        receipt_meta = payload.get("receipt_meta") or {}

        existing_intent_id = (
            payload.get("existing_intent_id")
            or payload.get("parent_intent_id")
            or receipt_meta.get("existing_intent_id")
            or receipt_meta.get("parent_intent_id")
        )

        complete_balance = bool(
            payload.get("complete_balance") or receipt_meta.get("complete_balance")
        )

        settle_failed_intent = bool(
            payload.get("settle_failed_intent")
            or receipt_meta.get("settle_failed_intent")
        )

        # =====================================================
        # CHANGE MODEL
        # =====================================================

        tendered_total = payload.get("tendered_total")
        change_amount = payload.get("change_amount")
        change_given_now = payload.get("change_given_now")
        tip_amount = payload.get("tip_amount")
        unpaid_amount = payload.get("unpaid_amount")
        note = payload.get("note")

        change_amount_d = _d(change_amount)
        change_given_now_d = _d(change_given_now)
        tip_amount_d = _d(tip_amount)

        safe_given_d = min(change_given_now_d, change_amount_d)

        safe_tip_d = min(
            tip_amount_d,
            max(Decimal("0"), change_amount_d - safe_given_d),
        )

        change_remaining_d = max(
            Decimal("0"),
            change_amount_d - (safe_given_d + safe_tip_d),
        )

        receipt_meta = {
            **receipt_meta,
            "document_type": "receipt",
            "tendered_total": float(_d(tendered_total))
            if tendered_total is not None
            else float(_d(receipt_meta.get("tendered_total"))),
            "change_amount": float(change_amount_d),
            "change_given_now": float(safe_given_d),
            "change_remaining": float(change_remaining_d),
            "tip_amount": float(safe_tip_d),
            "unpaid_amount": float(_d(unpaid_amount))
            if unpaid_amount is not None
            else float(_d(receipt_meta.get("unpaid_amount"))),
            "existing_intent_id": existing_intent_id,
            "parent_intent_id": existing_intent_id,
            "complete_balance": complete_balance or None,
            "settle_failed_intent": settle_failed_intent or None,
        }

        change_given_now = safe_given_d
        tip_amount = safe_tip_d
        change_remaining = change_remaining_d

        is_manual = bool(receipt_meta.get("manual"))

        if not client_reference:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="client_reference required",
            )

        if not lines:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="lines required",
            )

        ar = None

        # =====================================================
        # ORDER FLOW
        # =====================================================
        if order_id:
            sale = self._resolve_sale_from_order(
                db=db,
                tenant_id=tenant_id,
                branch_id=branch_id,
                user_id=user_id,
                order_id=int(order_id),
            )

            intent = PaymentIntentRepository.get_by_payable(
                db,
                tenant_id=tenant_id,
                payable_type="sale",
                payable_id=sale.id,
            )

            if not intent:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="PaymentIntent missing for resolved sale",
                )

            intent = PaymentService.apply_pos_settlement(
                db=db,
                tenant_id=tenant_id,
                branch_id=branch_id,
                sale_id=sale.id,
                existing_intent_id=existing_intent_id,
                complete_balance=complete_balance,
                settle_failed_intent=settle_failed_intent,
                created_by_user_id=user_id,
                client_reference=str(client_reference),
                lines=lines,
                tendered_total=_d(tendered_total)
                if tendered_total is not None
                else None,
                change_amount=_d(change_amount)
                if change_amount is not None
                else None,
                change_given_now=_d(change_given_now)
                if change_given_now is not None
                else None,
                change_remaining=_d(change_remaining)
                if change_remaining is not None
                else None,
                tip_amount=_d(tip_amount)
                if tip_amount is not None
                else None,
                unpaid_amount=_d(unpaid_amount)
                if unpaid_amount is not None
                else None,
                note=note,
                receipt_meta=receipt_meta,
            )

            ar = self._apply_order_settlement_status_and_ar(
                db=db,
                tenant_id=tenant_id,
                branch_id=branch_id,
                user_id=user_id,
                order_id=int(order_id),
                sale=sale,
                intent=intent,
                receipt_meta=receipt_meta,
                note=note,
            )

        # =====================================================
        # MANUAL / DIRECT PAY FLOW
        # =====================================================
        else:
            if not is_manual:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="order_id required (or manual mode)",
                )

            intent = PaymentService.apply_pos_settlement(
                db=db,
                tenant_id=tenant_id,
                branch_id=branch_id,
                sale_id=None,
                existing_intent_id=existing_intent_id,
                complete_balance=complete_balance,
                settle_failed_intent=settle_failed_intent,
                created_by_user_id=user_id,
                client_reference=str(client_reference),
                lines=lines,
                tendered_total=_d(tendered_total)
                if tendered_total is not None
                else None,
                change_amount=_d(change_amount)
                if change_amount is not None
                else None,
                change_given_now=_d(change_given_now)
                if change_given_now is not None
                else None,
                change_remaining=_d(change_remaining)
                if change_remaining is not None
                else None,
                tip_amount=_d(tip_amount)
                if tip_amount is not None
                else None,
                unpaid_amount=_d(unpaid_amount)
                if unpaid_amount is not None
                else None,
                note=note,
                receipt_meta={
                    **receipt_meta,
                    "manual": True,
                    "document_type": "receipt",
                },
            )

        db.commit()
        db.refresh(intent)

        return {
            "status": "ok",
            "order_id": int(order_id) if order_id else None,
            "sale_id": intent.payable_id
            if intent.payable_type == "sale"
            else None,
            "payable_type": intent.payable_type,
            "payable_id": intent.payable_id,
            "intent_id": intent.id,
            "total_paid": float(intent.total_paid or 0),
            "balance_due": float(intent.balance_due or 0),
            "receipt_meta": intent.meta or {},
            "intent_status": _status_ui(intent.status),
            "completed_existing_intent": bool(existing_intent_id),
            "ar_id": ar.id if ar else None,
            "ar_status": ar.status if ar else None,
        }

    # =====================================================
    # XAFPAY INIT (ORDER-DRIVEN)
    # =====================================================

    async def init_xafpay_payment(
        self,
        request: Request,
        payload: Dict[str, Any],
        db: Session,
    ):
        ctx = self._get_ctx(request)

        tenant_id = ctx["tenant_id"]
        branch_id = ctx["branch_id"]
        user_id = ctx["user_id"]

        order_id = payload.get("order_id")
        rail = payload.get("provider")

        if not order_id or not rail:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="order_id and provider required",
            )

        sale = self._resolve_sale_from_order(
            db=db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            user_id=user_id,
            order_id=int(order_id),
        )

        intent = PaymentIntentRepository.get_by_payable(
            db,
            tenant_id=tenant_id,
            payable_type="sale",
            payable_id=sale.id,
        )

        if not intent:
            intent = PaymentService.init_intent(
                db=db,
                tenant_id=tenant_id,
                branch_id=branch_id,
                payable_type="sale",
                payable_id=sale.id,
                currency="XAF",
                amount=Decimal(str(sale.total or 0)),
                channel="xafpay",
                created_by_user_id=user_id,
                client_reference=str(uuid.uuid4()),
                meta={
                    "sale_id": sale.id,
                    "order_id": int(order_id),
                    "receipt_no": getattr(sale, "receipt_no", None),
                },
            )
            db.flush()

        web_base = settings.WEB_BASE_URL.rstrip("/")

        return_url = (
            payload.get("returnUrl")
            or f"{web_base}/result?status=success&orderId={order_id}&saleId={sale.id}&intentId={intent.id}"
        )

        cancel_url = (
            payload.get("cancelUrl")
            or f"{web_base}/result?status=failure&orderId={order_id}&saleId={sale.id}"
        )

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(
                    f"{settings.GATEWAY_BASE_URL}/api/v1/payment-intents",
                    headers={
                        "Content-Type": "application/json",
                        "x-api-key": settings.GATEWAY_API_KEY,
                        "Idempotency-Key": str(uuid.uuid4()),
                    },
                    json={
                        "amount": float(intent.amount or 0),
                        "currency": intent.currency,
                        "provider": "tranzak",
                        "requestedRail": rail,
                        "externalId": str(intent.id),
                        "returnUrl": return_url,
                        "cancelUrl": cancel_url,
                    },
                )

            if response.status_code not in (200, 201):
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=response.text,
                )

            gateway_data = response.json()

        except httpx.RequestError:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Gateway connection failed",
            )

        gateway_intent_id = gateway_data.get("id")
        payment_url = gateway_data.get("paymentUrl")

        PaymentIntentRepository.set_gateway_id(
            intent=intent,
            gateway_intent_id=gateway_intent_id,
        )

        db.commit()

        return {
            "intent_id": intent.id,
            "order_id": int(order_id),
            "sale_id": sale.id,
            "gateway_intent_id": gateway_intent_id,
            "paymentUrl": payment_url,
        }