import os
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from core.domain.accounting.models import TreasuryLog
from core.domain.payments.models import PaymentIntent
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
from core.integrations.xafpay_v2.client import XafPayV2Client
from core.integrations.xafpay_v2.contract import XafPayV2IntegrationError
from core.integrations.xafpay_v2.wnd_service import WndXafPayV2Service


def _d(v: Any) -> Decimal:
    try:
        if v is None or v == "":
            return Decimal("0")
        return Decimal(str(v))
    except Exception:
        return Decimal("0")


def _gateway_execution_status(payment_id: str) -> Dict[str, Any]:
    base_url = os.environ.get("XAFPAY_V2_GATEWAY_BASE_URL", "").strip()
    credential = os.environ.get("XAFPAY_V2_SERVICE_CREDENTIAL", "").strip()
    if not base_url or not credential:
        raise XafPayV2IntegrationError("gateway_status_config_missing", "Gateway execution status unavailable")
    return XafPayV2Client(base_url, credential).payment_execution_status(payment_id)


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


def _canonical_xafpay_attempts(
    db: Session, tenant_id: int, sale_id: int
) -> List[Dict[str, Any]]:
    """Project neutral Finance attempts into the legacy Payments read surface."""
    rows = db.execute(text("""
        SELECT a.public_id,a.attempt_state,a.attempted_amount,a.payment_method_code,
               a.payment_rail_code,a.orchestrator_code,a.underlying_provider_code,
               a.occurred_at,a.external_attempt_reference,a.metadata,
               (SELECT count(*) FROM payment_settlements s
                 WHERE s.tenant_id=a.tenant_id AND s.payment_attempt_id=a.id
                   AND s.settlement_state='confirmed') AS confirmed_settlements
          FROM canonical_payment_attempts a
         WHERE a.tenant_id=:tenant_id
           AND a.metadata->>'sale_id'=:sale_id
           AND a.orchestrator_code='xafpay'
         ORDER BY a.occurred_at,a.id
    """), {"tenant_id": tenant_id, "sale_id": str(sale_id)}).mappings().all()
    projected = []
    for row in rows:
        status_value = _status_ui(row["attempt_state"])
        # This list projection is deliberately local-only. Canonical attempts
        # are created at provider-execution initiation; checkout proposals do
        # not enter this table. Live Gateway interrogation belongs exclusively
        # to explicit recovery/status operations.
        # A locally persisted external reference is the durable execution
        # boundary. Proposal/draft rows have no Gateway reference and remain
        # outside Payment Records; no live lookup is needed to decide this.
        provider_submitted = bool(row["external_attempt_reference"])
        if not provider_submitted:
            continue
        projected.append({
            "id": str(row["public_id"]),
            "provider": row["underlying_provider_code"] or "xafpay",
            "orchestrator": row["orchestrator_code"],
            "method": str(row["payment_method_code"] or "mobile_money").lower(),
            "rail": str(row["payment_rail_code"] or "").lower() or None,
            "origin_channel": "pos",
            "settlement_mode": "async_gateway",
            "amount": float(row["attempted_amount"] or 0),
            "status": status_value,
            "provider_submitted": provider_submitted,
            "confirmed_settlements": int(row["confirmed_settlements"] or 0),
            "created_at": row["occurred_at"].isoformat() if row["occurred_at"] else None,
            "gateway_reference": row["external_attempt_reference"],
            "meta": {**(row["metadata"] or {}), "financial_effect": "NONE_UNTIL_CANONICAL_SUCCESS"},
        })
    return projected


def _payment_record_summary(
    db: Session, intent: Any, attempts: List[Any], canonical_attempts: List[Dict[str, Any]]
) -> Dict[str, Any]:
    successful_local = [
        attempt for attempt in attempts
        if _status_ui(getattr(attempt, "status", None)) == "COMPLETED"
    ]
    local_methods = {
        str(attempt.method).lower() for attempt in successful_local
        if getattr(attempt, "method", None)
    }
    successful_canonical = [
        attempt for attempt in canonical_attempts
        if attempt["status"] == "COMPLETED"
        and int(attempt.get("confirmed_settlements") or 0) > 0
    ]
    active_pending = sum(
        1 for attempt in attempts
        if _status_ui(getattr(attempt, "status", None)) == "PENDING"
    ) + sum(1 for attempt in canonical_attempts if attempt["status"] == "PENDING")
    approved_ar = 0.0
    if intent.payable_type == "sale":
        approved_ar = float(db.execute(text("""
            SELECT coalesce(sum(balance_due),0) FROM accounts_receivable
             WHERE tenant_id=:tenant AND sale_id=:sale AND status IN ('open','partial')
        """), {"tenant": intent.tenant_id, "sale": int(intent.payable_id)}).scalar_one() or 0)

    has_mixed_authority = bool(local_methods and successful_canonical)
    if has_mixed_authority or len(local_methods) > 1:
        method, provider, orchestrator, rail = "split", None, None, None
    elif successful_canonical:
        latest = successful_canonical[-1]
        method, provider = latest["method"], latest["provider"]
        orchestrator, rail = latest["orchestrator"], latest["rail"]
    elif local_methods:
        method = next(iter(local_methods))
        latest_local = successful_local[-1]
        provider = getattr(latest_local, "provider", None)
        orchestrator, rail = None, None
    else:
        method, provider = intent.channel, None
        orchestrator, rail = None, None

    paid, due = float(intent.total_paid or 0), float(intent.balance_due or 0)
    if due <= 0:
        aggregate_state = "COMPLETED"
    elif approved_ar > 0:
        aggregate_state = "RECEIVABLE"
    elif active_pending > 0:
        aggregate_state = "PENDING"
    elif paid > 0:
        aggregate_state = "PARTIAL"
    else:
        aggregate_state = "PAYMENT_REQUIRED"
    return {
        "method": method, "provider": provider, "orchestrator": orchestrator,
        "rail": rail, "status": aggregate_state, "approved_ar": approved_ar,
        "active_pending_attempts": active_pending,
    }


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
        external_pending_amount: Decimal = Decimal("0"),
        accounts_receivable_amount: Decimal = Decimal("0"),
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

        if accounts_receivable_amount <= 0:
            if external_pending_amount > 0:
                order.status = "pending_payment"
                db.add(order)
            return None

        ar = AccountsReceivableService.create_or_update_from_settlement(
            db,
            tenant_id=tenant_id,
            branch_id=branch_id,
            order_id=int(order_id),
            sale_id=getattr(sale, "id", None),
            payment_intent_id=str(getattr(intent, "id", "") or ""),
            original_amount=original_amount_d,
            paid_amount=total_paid_d,
            balance_due=accounts_receivable_amount,
            customer_name=_extract_customer_name(receipt_meta),
            customer_phone=_extract_customer_phone(receipt_meta),
            note=_extract_note(receipt_meta, note),
            created_by_user_id=user_id,
        )

        if external_pending_amount > 0:
            order.status = "pending_payment"
        else:
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

            canonical_attempts = (
                _canonical_xafpay_attempts(db, tenant_id, int(intent.payable_id))
                if intent.payable_type == "sale" else []
            )
            summary = _payment_record_summary(db, intent, attempts, canonical_attempts)

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
                    "method": summary["method"],
                    "provider": summary["provider"],
                    "origin_channel": "pos" if canonical_attempts else intent.channel,
                    "orchestrator": summary["orchestrator"],
                    "rail": summary["rail"],
                    "status": summary["status"],
                    "approved_ar": summary["approved_ar"],
                    "active_pending_attempts": summary["active_pending_attempts"],
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

        intent = PaymentIntentRepository.get_by_id(
            db=db,
            tenant_id=tenant_id,
            intent_id=payment_id,
        )

        if not intent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Payment not found",
            )

        attempts = PaymentAttemptRepository.list_for_intent(
            db=db,
            intent_id=intent.id,
        )
        canonical_attempts = (
            _canonical_xafpay_attempts(db, tenant_id, int(intent.payable_id))
            if intent.payable_type == "sale" else []
        )
        projected_attempts = [{
            "id": str(a.id), "provider": a.provider, "method": a.method,
            "settlement_mode": a.settlement_mode, "amount": float(a.amount or 0),
            "status": _status_ui(a.status),
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "meta": a.meta or {},
        } for a in attempts] + canonical_attempts
        summary = _payment_record_summary(db, intent, attempts, canonical_attempts)

        return {
            "id": str(intent.id),
            "sale_id": intent.payable_id
            if intent.payable_type == "sale"
            else None,
            "payable_type": intent.payable_type,
            "payable_id": intent.payable_id,
            "amount": float(intent.amount or 0),
            "currency": intent.currency,
            "method": summary["method"],
            "origin_channel": "pos" if canonical_attempts else intent.channel,
            "orchestrator": summary["orchestrator"],
            "rail": summary["rail"],
            "provider": summary["provider"],
            "status": summary["status"],
            "approved_ar": summary["approved_ar"],
            "active_pending_attempts": summary["active_pending_attempts"],
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
            "attempts": projected_attempts,
        }

    async def xafpay_attempt_status(
        self, request: Request, attempt_public_id: str, db: Session
    ):
        """Project status only from XBOS canonical attempt/settlement truth."""
        ctx = self._get_ctx(request)
        row = db.execute(text("""
            SELECT a.public_id,a.attempt_state,a.attempted_amount,a.currency_code,
                   a.payment_rail_code,a.external_attempt_reference,a.metadata,
                   (SELECT pi.id FROM payment_intents pi
                     WHERE pi.tenant_id=a.tenant_id AND pi.payable_type='sale'
                       AND pi.payable_id=(a.metadata->>'sale_id')::int
                     ORDER BY pi.id DESC LIMIT 1) AS payment_record_id,
                   (SELECT count(*) FROM payment_settlements s
                     WHERE s.tenant_id=a.tenant_id AND s.payment_attempt_id=a.id
                       AND s.settlement_state='confirmed') AS confirmed_settlements,
                   (SELECT pi.amount FROM payment_intents pi
                     WHERE pi.tenant_id=a.tenant_id AND pi.payable_type='sale'
                       AND pi.payable_id=(a.metadata->>'sale_id')::int
                     ORDER BY pi.id DESC LIMIT 1) AS commercial_total,
                   (SELECT pi.total_paid FROM payment_intents pi
                     WHERE pi.tenant_id=a.tenant_id AND pi.payable_type='sale'
                       AND pi.payable_id=(a.metadata->>'sale_id')::int
                     ORDER BY pi.id DESC LIMIT 1) AS total_paid,
                   (SELECT pi.balance_due FROM payment_intents pi
                     WHERE pi.tenant_id=a.tenant_id AND pi.payable_type='sale'
                       AND pi.payable_id=(a.metadata->>'sale_id')::int
                     ORDER BY pi.id DESC LIMIT 1) AS balance_due,
                   (SELECT coalesce(sum(ar.balance_due),0) FROM accounts_receivable ar
                     WHERE ar.tenant_id=a.tenant_id
                       AND ar.sale_id=(a.metadata->>'sale_id')::int
                       AND ar.status IN ('open','partial')) AS approved_ar
              FROM canonical_payment_attempts a
             WHERE a.tenant_id=:tenant_id AND a.public_id::text=:attempt_id
               AND a.orchestrator_code='xafpay'
        """), {"tenant_id": ctx["tenant_id"], "attempt_id": attempt_public_id}).mappings().one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="XafPay attempt not found")
        state = str(row["attempt_state"] or "pending").lower()
        execution = _gateway_execution_status(str(row["external_attempt_reference"]))
        provider_submitted = bool(execution.get("providerSubmitted"))
        projected_state = state.upper() if provider_submitted else "CHECKOUT_OPEN"
        settlements = int(row["confirmed_settlements"] or 0)
        commercial_total = float(row["commercial_total"] or 0)
        sale_id = int((row["metadata"] or {}).get("sale_id"))
        confirmed_local = db.execute(text("""
            SELECT amount FROM payment_attempts
             WHERE payment_intent_id=(SELECT id FROM payment_intents
                                       WHERE tenant_id=:tenant AND payable_type='sale'
                                         AND payable_id=:sale ORDER BY id DESC LIMIT 1)
               AND lower(status) IN ('succeeded','success','completed','complete','paid')
               AND lower(coalesce(method,'')) <> 'xafpay'
             ORDER BY created_at,id
        """), {"tenant": ctx["tenant_id"], "sale": sale_id}).scalars().all()
        total_paid = 0.0
        for confirmed_amount in confirmed_local:
            amount = float(confirmed_amount or 0)
            if amount > 0 and amount <= commercial_total - total_paid:
                total_paid += amount
        confirmed_xafpay = db.execute(text("""
            SELECT coalesce(sum(s.gross_amount),0)
              FROM payment_settlements s
              JOIN canonical_payment_attempts a
                ON a.tenant_id=s.tenant_id AND a.id=s.payment_attempt_id
             WHERE s.tenant_id=:tenant AND a.metadata->>'sale_id'=:sale
               AND a.orchestrator_code='xafpay'
               AND s.settlement_state IN ('confirmed','partially_reversed')
        """), {"tenant": ctx["tenant_id"], "sale": str(sale_id)}).scalar_one()
        total_paid = min(commercial_total, total_paid + float(confirmed_xafpay or 0))
        balance_due = max(0.0, commercial_total - total_paid)
        approved_ar = float(row["approved_ar"] or 0)
        return {
            "attempt_public_id": str(row["public_id"]),
            "attempt_state": projected_state,
            "provider_submitted": provider_submitted,
            "gateway_attempt_id": execution.get("attemptId"),
            "gateway_attempt_state": execution.get("attemptStatus"),
            "amount": float(row["attempted_amount"]),
            "currency": row["currency_code"],
            "rail": row["payment_rail_code"],
            "gateway_payment_id": row["external_attempt_reference"],
            "order_id": (row["metadata"] or {}).get("order_id"),
            "sale_id": (row["metadata"] or {}).get("sale_id"),
            "payment_record_id": str(row["payment_record_id"]),
            "confirmed_settlements": settlements,
            "financially_confirmed": state == "succeeded" and settlements == 1,
            "commercial_total": commercial_total,
            "total_paid": total_paid,
            "balance_due": balance_due,
            "approved_ar": approved_ar,
            "collectible_now": max(0.0, balance_due - approved_ar),
        }

    async def xafpay_order_recovery(
        self, request: Request, order_id: int, db: Session
    ):
        """Return only the latest XafPay state for this exact WND obligation."""
        ctx = self._get_ctx(request)
        row = db.execute(text("""
            SELECT a.public_id,a.attempt_state,a.attempted_amount,
                   a.payment_rail_code,a.external_attempt_reference,a.metadata,
                   (SELECT pi.id FROM payment_intents pi
                     WHERE pi.tenant_id=a.tenant_id AND pi.payable_type='sale'
                       AND pi.payable_id=(a.metadata->>'sale_id')::int
                     ORDER BY pi.id DESC LIMIT 1) AS payment_record_id,
                   (SELECT count(*) FROM payment_settlements s
                     WHERE s.tenant_id=a.tenant_id AND s.payment_attempt_id=a.id
                       AND s.settlement_state='confirmed') confirmed_settlements
              FROM canonical_payment_attempts a
             WHERE a.tenant_id=:tenant AND a.organization_unit_id=:branch
               AND a.metadata->>'order_id'=:order_id
               AND a.orchestrator_code='xafpay'
             ORDER BY a.occurred_at DESC,a.id DESC LIMIT 1
        """), {"tenant": ctx["tenant_id"], "branch": ctx["branch_id"],
                 "order_id": str(order_id)}).mappings().one_or_none()
        if row is None:
            return {"order_id": order_id, "has_xafpay_attempt": False,
                    "unresolved": False}
        state = str(row["attempt_state"] or "pending").lower()
        execution = _gateway_execution_status(str(row["external_attempt_reference"]))
        provider_submitted = bool(execution.get("providerSubmitted"))
        unresolved = provider_submitted and state in {"pending", "processing", "unknown"}
        return {
            "order_id": order_id,
            "sale_id": (row["metadata"] or {}).get("sale_id"),
            "payment_record_id": str(row["payment_record_id"]),
            "has_xafpay_attempt": provider_submitted,
            "has_checkout_proposal": not provider_submitted,
            "unresolved": unresolved,
            "attempt_public_id": str(row["public_id"]),
            "attempt_state": state.upper() if provider_submitted else "CHECKOUT_OPEN",
            "provider_submitted": provider_submitted,
            "gateway_attempt_id": execution.get("attemptId"),
            "gateway_attempt_state": execution.get("attemptStatus"),
            "amount": float(row["attempted_amount"]),
            "rail": row["payment_rail_code"],
            "gateway_payment_id": row["external_attempt_reference"],
            "confirmed_settlements": int(row["confirmed_settlements"] or 0),
        }

    async def request_xafpay_cancellation(
        self, request: Request, attempt_public_id: str, db: Session
    ):
        """Fail closed unless canonical evidence already makes replacement safe.

        Tranzak's current adapter has query/refresh operations but no verified
        in-flight cancellation operation. An operator request therefore never
        mutates attempt or financial state.
        """
        projection = await self.xafpay_attempt_status(
            request=request, attempt_public_id=attempt_public_id, db=db
        )
        state = str(projection["attempt_state"]).upper()
        settlements = int(projection["confirmed_settlements"] or 0)
        if state == "SUCCEEDED" or settlements > 0:
            return {
                **projection,
                "cancellation_state": "UNAVAILABLE_SUCCEEDED",
                "replacement_tender_allowed": False,
                "message": "Payment is already confirmed. Cancellation is unavailable.",
            }
        if state in {"FAILED", "EXPIRED", "CANCELLED", "CANCELED"}:
            return {
                **projection,
                "cancellation_state": "TERMINAL_CONFIRMED",
                "replacement_tender_allowed": True,
                "message": "The prior attempt is terminal. No money was collected; choose another payment method.",
            }
        return {
            **projection,
            "cancellation_state": "UNCONFIRMED",
            "replacement_tender_allowed": False,
            "message": "Cancellation is not yet confirmed. This payment may still complete. Do not collect another payment yet.",
        }

    # =====================================================
    # PAYMENTS ACTIVITY READ MODEL
    # =====================================================

    async def list_activity(self, request: Request, db: Session, limit: int = 100):
        """Read-only projection: unresolved external attempts are attention, never money."""
        ctx = self._get_ctx(request)
        tenant_id, branch_id = ctx["tenant_id"], ctx["branch_id"]
        safe_limit = max(10, min(int(limit or 100), 250))
        posted_types = (
            "PAYMENT_RECEIVED", "DEBT_REPAYMENT", "OTHER_INCOME", "SERVICE_REVENUE",
            "EXPENSE_POSTED", "REFUND_PAID", "CASH_MOVE",
        )
        events = (
            db.query(TreasuryLog)
            .filter(TreasuryLog.tenant_id == tenant_id, TreasuryLog.branch_id == branch_id,
                    TreasuryLog.event_type.in_(posted_types))
            .order_by(TreasuryLog.occurred_at.desc(), TreasuryLog.id.desc())
            .limit(safe_limit * 3).all()
        )
        unresolved = (
            db.query(PaymentIntent)
            .filter(PaymentIntent.tenant_id == tenant_id, PaymentIntent.branch_id == branch_id,
                    PaymentIntent.status.in_(("pending", "processing", "failed", "cancelled")))
            .order_by(PaymentIntent.created_at.desc(), PaymentIntent.id.desc())
            .limit(safe_limit).all()
        )
        xafpay_settlements = db.execute(text("""
            SELECT s.id,s.public_id,s.gross_amount,s.currency_code,s.occurred_at,
                   a.external_attempt_reference,a.metadata,a.payment_rail_code
              FROM payment_settlements s
              JOIN canonical_payment_attempts a
                ON a.tenant_id=s.tenant_id AND a.id=s.payment_attempt_id
             WHERE s.tenant_id=:tenant_id AND s.organization_unit_id=:branch_id
               AND a.orchestrator_code='xafpay'
               AND s.settlement_state IN ('confirmed','partially_reversed')
             ORDER BY s.occurred_at DESC,s.id DESC LIMIT :limit
        """), {"tenant_id": tenant_id, "branch_id": branch_id, "limit": safe_limit}).mappings().all()

        def clean(value):
            selected = str(value or "").strip()
            return selected or None

        incoming = {"PAYMENT_RECEIVED", "DEBT_REPAYMENT", "OTHER_INCOME", "SERVICE_REVENUE"}
        outgoing = {"EXPENSE_POSTED", "REFUND_PAID"}
        labels = {"PAYMENT_RECEIVED": "Sale payment", "DEBT_REPAYMENT": "A/R payment",
                  "OTHER_INCOME": "Income", "SERVICE_REVENUE": "Income",
                  "EXPENSE_POSTED": "Expense", "REFUND_PAID": "Refund", "CASH_MOVE": "Transfer"}
        rows = []
        for event in events:
            metadata, event_type = event.meta or {}, str(event.event_type or "").upper()
            reference = metadata.get("reference") or metadata.get("client_reference")
            if not reference and event.reference_type and event.reference_id:
                reference = f"{event.reference_type} #{event.reference_id}"
            rows.append({
                "id": f"event:{event.id}", "source": "treasury_event", "source_id": event.id,
                "activity_type": labels.get(event_type, event_type.replace("_", " ").title()),
                "event_type": event_type, "status": "POSTED",
                "flow": "in" if event_type in incoming else "out" if event_type in outgoing else "transfer",
                "amount": float(event.amount or 0), "currency": str(event.currency or "XAF"),
                "channel": clean(event.channel) or "—", "reference": clean(reference),
                "detail": clean(metadata.get("note") or metadata.get("item_name")),
                "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
                "document_type": None, "_sort_at": event.occurred_at or event.created_at,
            })
        for settlement in xafpay_settlements:
            metadata, occurred = settlement["metadata"] or {}, settlement["occurred_at"]
            order_id = metadata.get("order_id")
            rows.append({
                "id": f"settlement:{settlement['public_id']}", "source": "payment_settlement",
                "source_id": settlement["id"], "activity_type": "XafPay payment",
                "event_type": "PAYMENT_SETTLED", "status": "CONFIRMED", "flow": "in",
                "amount": float(settlement["gross_amount"] or 0),
                "currency": str(settlement["currency_code"] or "XAF"), "channel": "xafpay",
                "reference": f"Order #{order_id}" if order_id else clean(settlement["external_attempt_reference"]),
                "detail": clean(settlement["payment_rail_code"]),
                "occurred_at": occurred.isoformat() if occurred else None,
                "document_type": "payment_receipt", "_sort_at": occurred,
            })
        for intent in unresolved:
            raw_status = str(getattr(intent.status, "value", intent.status) or "pending").lower()
            recovery = None
            if intent.payable_type == "sale":
                xafpay_attempts = _canonical_xafpay_attempts(
                    db, tenant_id, int(intent.payable_id)
                )
                if xafpay_attempts:
                    latest = xafpay_attempts[-1]
                    if latest["status"] == "PENDING":
                        recovery = {
                            "attempt_public_id": latest["id"],
                            "order_id": latest["meta"].get("order_id"),
                            "sale_id": int(intent.payable_id),
                            "payment_record_id": str(intent.id),
                            "rail": latest["rail"],
                            "orchestrator": latest["orchestrator"],
                        }
            rows.append({
                "id": f"intent:{intent.id}", "source": "payment_intent", "source_id": intent.id,
                "activity_type": "Outstanding payment", "event_type": "PAYMENT_INTENT",
                "status": raw_status.upper(), "flow": "attention",
                "amount": float(intent.balance_due or intent.amount or 0),
                "currency": str(intent.currency or "XAF"), "channel": clean(intent.channel) or "—",
                "reference": f"{str(intent.payable_type).title()} #{intent.payable_id}", "detail": None,
                "occurred_at": intent.created_at.isoformat() if intent.created_at else None,
                "document_type": None, "recovery": recovery,
                "_sort_at": intent.created_at,
            })
        rows.sort(key=lambda row: (row["_sort_at"] is not None, row["_sort_at"], row["id"]), reverse=True)
        rows = rows[:safe_limit]
        for row in rows:
            row.pop("_sort_at", None)
        business_tz = ZoneInfo("Africa/Douala")
        now_local = datetime.now(business_tz)
        window_start = now_local.replace(hour=8, minute=0, second=0, microsecond=0)
        if now_local < window_start:
            window_start -= timedelta(days=1)
        window_end = window_start + timedelta(days=1)
        window_rows = [row for row in rows if row.get("occurred_at") and
                       window_start <= datetime.fromisoformat(row["occurred_at"]) < window_end]
        return {
            "window": {"label": "Current business day", "timezone": "Africa/Douala",
                       "start": window_start.isoformat(), "end": window_end.isoformat()},
            "summary": {"received": sum(row["amount"] for row in window_rows if row["flow"] == "in"),
                        "paid_out": sum(row["amount"] for row in window_rows if row["flow"] == "out"),
                        "transferred": sum(row["amount"] for row in window_rows if row["flow"] == "transfer"),
                        "attention": sum(1 for row in rows if row["flow"] == "attention")},
            "count": len(rows), "items": rows,
        }

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

        if order_id:
            unresolved = db.execute(text("""
                SELECT a.public_id,a.attempt_state,a.attempted_amount,a.external_attempt_reference
                  FROM canonical_payment_attempts a
                 WHERE a.tenant_id=:tenant AND a.organization_unit_id=:branch
                   AND a.metadata->>'order_id'=:order_id
                   AND a.orchestrator_code='xafpay'
                   AND a.attempt_state IN ('pending','processing','unknown')
                 ORDER BY a.occurred_at DESC,a.id DESC LIMIT 1
            """), {"tenant": tenant_id, "branch": branch_id,
                     "order_id": str(order_id)}).mappings().one_or_none()
            if unresolved is not None:
                try:
                    execution = _gateway_execution_status(str(unresolved["external_attempt_reference"]))
                except XafPayV2IntegrationError:
                    execution = {"providerSubmitted": True}  # fail closed on status loss
                if bool(execution.get("providerSubmitted")):
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={
                            "code": "XAFPAY_UNRESOLVED_OBLIGATION",
                            "attempt_public_id": str(unresolved["public_id"]),
                            "attempt_state": str(unresolved["attempt_state"]).upper(),
                            "amount": float(unresolved["attempted_amount"]),
                        },
                    )

        if any(
            str(line.get("method") or "").strip().lower() == "xafpay"
            or str(line.get("settlement_mode") or "").strip().lower() == "async_gateway"
            for line in lines
            if isinstance(line, dict)
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="XafPay external payment must use /payments/xafpay/init and canonical confirmation",
            )

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
        external_pending_amount = _d(payload.get("external_pending_amount"))
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
                external_pending_amount=external_pending_amount,
                accounts_receivable_amount=_d(unpaid_amount),
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
        requested_amount = _d(payload.get("amount"))

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
                channel="pos",
                created_by_user_id=user_id,
                client_reference=str(uuid.uuid4()),
                meta={
                    "sale_id": sale.id,
                    "order_id": int(order_id),
                    "receipt_no": getattr(sale, "receipt_no", None),
                },
            )
            db.flush()

        available_balance = _d(getattr(intent, "balance_due", None) or getattr(intent, "amount", 0))
        if requested_amount <= 0:
            requested_amount = available_balance
        if requested_amount <= 0 or requested_amount > available_balance:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="XafPay allocation must be positive and no greater than the XBOS balance due",
            )

        base_url = os.environ.get("XAFPAY_V2_GATEWAY_BASE_URL", "").strip()
        credential = os.environ.get("XAFPAY_V2_SERVICE_CREDENTIAL", "").strip()
        presentation_url = os.environ.get("XAFPAY_V2_CHECKOUT_PRESENTATION_URL", "").strip()
        if not base_url or not credential or not presentation_url:
            raise HTTPException(status_code=503, detail="XafPay V2 rehearsal configuration unavailable")
        if not presentation_url.startswith("http://127.0.0.1:5174/xafpay-checkout"):
            raise HTTPException(status_code=503, detail="XafPay Checkout presentation origin unavailable")
        client_reference = str(payload.get("client_reference") or f"wnd-order-{order_id}")
        gateway_client = XafPayV2Client(base_url, credential)
        try:
            result = WndXafPayV2Service.initiate_order(
                db,
                tenant_id=tenant_id,
                organization_unit_id=branch_id,
                order_id=int(order_id),
                sale_id=int(sale.id),
                amount=requested_amount,
                rail=str(rail),
                client_reference=client_reference,
                client=gateway_client,
            )
            execution = gateway_client.payment_execution_status(result["gateway_payment_id"])
            db.commit()
        except XafPayV2IntegrationError as exc:
            db.rollback()
            diagnostic = str(exc)
            if len(diagnostic) > 500:
                diagnostic = diagnostic[:500]
            raise HTTPException(
                status_code=502,
                detail=f"XafPay V2 initiation failed: {exc.code}: {diagnostic}",
            ) from exc
        except Exception as exc:
            db.rollback()
            raise HTTPException(status_code=502, detail=f"XafPay V2 initiation failed: {type(exc).__name__}") from exc
        return {
            **result,
            "status": (
                str(execution.get("attemptStatus") or "PENDING").upper()
                if execution.get("providerSubmitted") else "CHECKOUT_OPEN"
            ),
            "provider_submitted": bool(execution.get("providerSubmitted")),
            "gateway_attempt_id": execution.get("attemptId"),
            "payment_record_id": str(intent.id),
            "paymentUrl": f"{presentation_url}#token={result['checkout_token']}",
        }
