import os
from decimal import Decimal
from typing import Any, Dict, List

from fastapi import HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.orm import Session

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
    # XAFPAY CURRENT CANONICAL STATUS / RECOVERY
    # =====================================================

    async def xafpay_attempt_status(
        self, request: Request, attempt_public_id: str, db: Session
    ):
        """Read only XBOS canonical attempt/settlement projection. No external calls."""
        ctx = self._get_ctx(request)
        row = db.execute(text("""
            SELECT a.public_id,a.attempt_state,a.attempted_amount,a.currency_code,
                   a.payment_rail_code,a.external_attempt_reference,a.metadata,
                   (SELECT count(*) FROM payment_settlements ps
                     WHERE ps.tenant_id=a.tenant_id AND ps.payment_attempt_id=a.id
                       AND ps.settlement_state IN ('confirmed','partially_reversed'))
                       AS confirmed_settlements,
                   (SELECT pi.id FROM payment_intents pi
                     WHERE pi.tenant_id=a.tenant_id AND pi.payable_type='sale'
                       AND pi.payable_id=(a.metadata->>'sale_id')::int
                     ORDER BY pi.id DESC LIMIT 1) AS payment_record_id,
                   (SELECT pi.total_paid FROM payment_intents pi
                     WHERE pi.tenant_id=a.tenant_id AND pi.payable_type='sale'
                       AND pi.payable_id=(a.metadata->>'sale_id')::int
                     ORDER BY pi.id DESC LIMIT 1) AS total_paid,
                   (SELECT pi.balance_due FROM payment_intents pi
                     WHERE pi.tenant_id=a.tenant_id AND pi.payable_type='sale'
                       AND pi.payable_id=(a.metadata->>'sale_id')::int
                     ORDER BY pi.id DESC LIMIT 1) AS balance_due
              FROM canonical_payment_attempts a
             WHERE a.tenant_id=:tenant_id
               AND a.organization_unit_id=:branch_id
               AND a.public_id::text=:attempt_id
               AND a.orchestrator_code='xafpay'
        """), {
            "tenant_id": ctx["tenant_id"],
            "branch_id": ctx["branch_id"],
            "attempt_id": attempt_public_id,
        }).mappings().one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="XafPay attempt not found")

        state_value = str(row["attempt_state"] or "pending").lower()
        metadata = dict(row["metadata"] or {})
        unresolved = state_value in {
            "pending", "processing", "requires_action", "authorized"
        }
        settlements = int(row["confirmed_settlements"] or 0)
        return {
            "attempt_public_id": str(row["public_id"]),
            "attempt_state": state_value.upper(),
            "unresolved": unresolved,
            "amount": float(row["attempted_amount"] or 0),
            "currency": str(row["currency_code"] or "").upper(),
            "rail": str(row["payment_rail_code"] or "").upper(),
            "gateway_payment_id": row["external_attempt_reference"],
            "checkout_session_id": metadata.get("checkout_session_id"),
            "checkout_status": metadata.get("checkout_status"),
            "presentation_state": (
                "PRESENTATION_EXPIRED"
                if metadata.get("checkout_status") == "EXPIRED"
                else "PRESENTABLE" if metadata.get("checkout_session_id") else None
            ),
            "order_id": metadata.get("order_id"),
            "sale_id": metadata.get("sale_id"),
            "payment_record_id": (
                str(row["payment_record_id"]) if row["payment_record_id"] is not None else None
            ),
            "confirmed_settlements": settlements,
            "financially_confirmed": state_value == "succeeded" and settlements == 1,
            "total_paid": float(row["total_paid"] or 0),
            "balance_due": float(row["balance_due"] or 0),
        }

    async def xafpay_order_recovery(
        self, request: Request, order_id: int, db: Session
    ):
        """Resolve the latest XafPay attempt for this WND obligation from XBOS only."""
        ctx = self._get_ctx(request)
        attempt_id = db.execute(text("""
            SELECT public_id
              FROM canonical_payment_attempts
             WHERE tenant_id=:tenant_id
               AND organization_unit_id=:branch_id
               AND metadata->>'order_id'=:order_id
               AND orchestrator_code='xafpay'
             ORDER BY occurred_at DESC,id DESC
             LIMIT 1
        """), {
            "tenant_id": ctx["tenant_id"],
            "branch_id": ctx["branch_id"],
            "order_id": str(order_id),
        }).scalar_one_or_none()
        if attempt_id is None:
            return {
                "order_id": order_id,
                "has_xafpay_attempt": False,
                "unresolved": False,
            }
        projection = await self.xafpay_attempt_status(
            request=request,
            attempt_public_id=str(attempt_id),
            db=db,
        )
        return {
            **projection,
            "has_xafpay_attempt": True,
            "resume_uses_same_attempt": bool(projection["unresolved"]),
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

        if any(
            isinstance(line, dict)
            and (
                str(line.get("method") or "").strip().lower() == "xafpay"
                or str(line.get("settlement_mode") or "").strip().lower() == "async_gateway"
                or str((line.get("meta") or {}).get("orchestrator") or "").strip().lower() == "xafpay"
            )
            for line in lines
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="XafPay external value requires canonical Gateway settlement",
            )

        if order_id:
            unresolved = db.execute(text("""
                SELECT public_id,attempt_state,attempted_amount
                  FROM canonical_payment_attempts
                 WHERE tenant_id=:tenant_id
                   AND organization_unit_id=:branch_id
                   AND metadata->>'order_id'=:order_id
                   AND orchestrator_code='xafpay'
                   AND attempt_state IN ('pending','processing','requires_action','authorized')
                 ORDER BY occurred_at DESC,id DESC
                 LIMIT 1
            """), {
                "tenant_id": tenant_id,
                "branch_id": branch_id,
                "order_id": str(order_id),
            }).mappings().one_or_none()
            if unresolved is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "XAFPAY_UNRESOLVED_OBLIGATION",
                        "attempt_public_id": str(unresolved["public_id"]),
                        "attempt_state": str(unresolved["attempt_state"]).upper(),
                        "amount": float(unresolved["attempted_amount"] or 0),
                    },
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
            "external_pending_amount": float(external_pending_amount),
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
        """Create/replay one current Gateway CheckoutSession for one XBOS XafPay attempt."""
        ctx = self._get_ctx(request)
        tenant_id = ctx["tenant_id"]
        branch_id = ctx["branch_id"]
        user_id = ctx["user_id"]

        order_id = payload.get("order_id")
        rail = payload.get("rail") or payload.get("provider")
        requested_amount = _d(payload.get("amount"))
        if not order_id or not rail:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="order_id and XafPay rail required",
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
                client_reference=f"wnd-xafpay-commercial:{tenant_id}:{order_id}:{sale.id}",
                meta={
                    "sale_id": sale.id,
                    "order_id": int(order_id),
                    "receipt_no": getattr(sale, "receipt_no", None),
                },
            )
            db.flush()

        available_balance = _d(
            getattr(intent, "balance_due", None) or getattr(intent, "amount", 0)
        )
        if requested_amount <= 0:
            requested_amount = available_balance
        if requested_amount <= 0 or requested_amount > available_balance:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="XafPay allocation must be positive and no greater than balance due",
            )

        base_url = os.environ.get("XAFPAY_V2_GATEWAY_BASE_URL", "").strip()
        credential = os.environ.get("XAFPAY_V2_SERVICE_CREDENTIAL", "").strip()
        presentation_url = os.environ.get(
            "XAFPAY_V2_CHECKOUT_PRESENTATION_URL", ""
        ).strip()
        if not base_url or not credential or not presentation_url:
            raise HTTPException(
                status_code=503,
                detail="XafPay V2 checkout configuration unavailable",
            )

        try:
            result = WndXafPayV2Service.initiate_order(
                db,
                tenant_id=tenant_id,
                organization_unit_id=branch_id,
                order_id=int(order_id),
                sale_id=int(sale.id),
                amount=requested_amount,
                rail=str(rail),
                client=XafPayV2Client(base_url, credential),
            )
            db.commit()
        except XafPayV2IntegrationError as exc:
            db.rollback()
            diagnostic = str(exc)[:500]
            raise HTTPException(
                status_code=502,
                detail=f"XafPay V2 checkout failed: {exc.code}: {diagnostic}",
            ) from exc
        except (ValueError, RuntimeError) as exc:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc

        token = result.get("checkout_token")
        payment_url = (
            f"{presentation_url.rstrip('/')}#token={token}"
            if token and result.get("presentation_state") == "PRESENTABLE"
            else None
        )
        return {
            **result,
            "intent_id": intent.id,
            "payment_record_id": str(intent.id),
            "paymentUrl": payment_url,
        }
