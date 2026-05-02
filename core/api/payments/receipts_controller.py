from typing import Dict, Any
from decimal import Decimal

from fastapi import Request, HTTPException
from sqlalchemy.orm import Session

from core.domain.sales.repository import SaleRepository
from core.domain.payments.repository import (
    PaymentIntentRepository,
    PaymentAttemptRepository,
)


def _d(v: Any) -> Decimal:
    try:
        if v is None or v == "":
            return Decimal("0")
        return Decimal(str(v))
    except Exception:
        return Decimal("0")


def _status_value(v: Any) -> str:
    """
    Normalize enum/string statuses safely.

    Handles:
    - PaymentAttemptStatus.succeeded
    - "succeeded"
    - "PaymentAttemptStatus.succeeded"
    - "SUCCEEDED"
    """
    raw = getattr(v, "value", v)
    text = str(raw or "").strip().lower()

    if "." in text:
        text = text.split(".")[-1]

    return text


def _is_success_status(v: Any) -> bool:
    return _status_value(v) in {
        "succeeded",
        "success",
        "paid",
        "settled",
        "completed",
    }


def _customer_payload(customer: Any):
    if isinstance(customer, dict):
        return {
            "name": customer.get("name"),
            "phone": customer.get("phone"),
        }

    if isinstance(customer, str) and customer.strip():
        return {"name": customer.strip()}

    return None


class ReceiptsController:

    async def get_receipt(
        self,
        *,
        request: Request,
        sale_id: int,
        db: Session,
    ) -> Dict[str, Any]:

        ctx = getattr(request.state, "user", None)
        if not ctx:
            raise HTTPException(status_code=401)

        tenant_id = ctx["tenant_id"]
        branch_id = ctx["branch_id"]

        sale = SaleRepository.get_by_id(
            db,
            tenant_id=tenant_id,
            sale_id=sale_id,
        )

        if not sale or sale.branch_id != branch_id:
            raise HTTPException(status_code=404, detail="Sale not found")

        intent = PaymentIntentRepository.get_by_payable(
            db,
            tenant_id=tenant_id,
            payable_type="sale",
            payable_id=sale.id,
        )

        if not intent:
            raise HTTPException(
                status_code=500,
                detail="PaymentIntent missing for sale",
            )

        return await self._build_receipt_from_intent(
            intent=intent,
            sale=sale,
            ctx=ctx,
            db=db,
        )

    async def get_manual_receipt(
        self,
        *,
        request: Request,
        intent_id: int,
        db: Session,
    ) -> Dict[str, Any]:

        ctx = getattr(request.state, "user", None)
        if not ctx:
            raise HTTPException(status_code=401)

        tenant_id = ctx["tenant_id"]

        intent = PaymentIntentRepository.get_by_id(
            db,
            tenant_id=tenant_id,
            intent_id=intent_id,
        )

        if not intent:
            raise HTTPException(
                status_code=404,
                detail="PaymentIntent not found",
            )

        return await self._build_receipt_from_intent(
            intent=intent,
            sale=None,
            ctx=ctx,
            db=db,
        )

    async def _build_receipt_from_intent(
        self,
        *,
        intent,
        sale,
        ctx,
        db,
    ) -> Dict[str, Any]:

        attempts = PaymentAttemptRepository.list_for_intent(
            db,
            intent_id=intent.id,
        )

        successful_attempts = [
            a for a in attempts
            if _is_success_status(a.status)
        ]

        meta = dict(intent.meta or {})

        # =====================================================
        # CORE TOTALS
        # =====================================================

        net_due = _d(intent.amount)

        attempts_paid = sum(
            (_d(a.amount) for a in successful_attempts),
            Decimal("0"),
        )

        stored_total_paid = _d(intent.total_paid or 0)

        # Backend receipt truth:
        # - use persisted total_paid when correct
        # - recover from successful attempts when persisted total is stale/zero
        # - cap applied amount to net_due so receipt does not over-apply tender
        total_paid = max(
            stored_total_paid,
            min(net_due, attempts_paid),
        )

        if total_paid < 0:
            total_paid = Decimal("0")

        balance_due = net_due - total_paid
        if balance_due < 0:
            balance_due = Decimal("0")

        # =====================================================
        # CHANGE / TIP MODEL
        # =====================================================

        change_amount = _d(meta.get("change_amount", 0))
        change_given_now = _d(meta.get("change_given_now", 0))
        tip_amount = _d(meta.get("tip_amount", 0))

        safe_given = min(change_given_now, change_amount)

        safe_tip = min(
            tip_amount,
            max(Decimal("0"), change_amount - safe_given),
        )

        change_remaining = max(
            Decimal("0"),
            change_amount - (safe_given + safe_tip),
        )

        # Keep returned meta consistent. We do not commit here; this endpoint
        # returns canonical receipt values without turning the receipt read path
        # into a write-heavy operation.
        meta["change_given_now"] = float(safe_given)
        meta["tip_amount"] = float(safe_tip)
        meta["change_remaining"] = float(change_remaining)

        # =====================================================
        # DESCRIPTIVE FIELDS
        # =====================================================

        description = meta.get("description")
        reference = meta.get("reference")
        customer_payload = _customer_payload(meta.get("customer"))

        gross_total = _d(meta.get("gross_total", net_due))
        discount_total = _d(meta.get("discount_total", 0))
        complimentary_total = _d(meta.get("complimentary_total", 0))

        # Tendered total is customer-facing tender, not applied amount.
        # If absent/stale, recover from attempts.
        tendered_total = _d(meta.get("tendered_total", 0))
        if tendered_total <= 0:
            tendered_total = attempts_paid if attempts_paid > 0 else total_paid

        # =====================================================
        # ITEMS / RECEIPT ID
        # =====================================================

        if sale:
            items = [
                {
                    "name": item.name_snapshot,
                    "unit_price": float(_d(item.unit_price)),
                    "quantity": item.quantity,
                    "line_total": float(_d(item.line_total)),
                }
                for item in sale.items
            ]

            receipt_no = sale.receipt_no
            created_at = sale.created_at.isoformat()

        else:
            raw_items = meta.get("items")

            if isinstance(raw_items, list) and raw_items:
                items = raw_items
            else:
                items = [
                    {
                        "name": description or reference or "Payment",
                        "unit_price": float(net_due),
                        "quantity": 1,
                        "line_total": float(net_due),
                    }
                ]

            receipt_no = (
                meta.get("receipt_no")
                or meta.get("reference")
                or f"MP-{intent.id}"
            )

            created_at = (
                intent.created_at.isoformat()
                if getattr(intent, "created_at", None)
                else None
            )

        # =====================================================
        # PAYMENTS PAYLOAD
        # =====================================================

        payments_payload = [
            {
                "method": str(a.method),
                "provider": str(a.provider) if a.provider else None,
                "amount": float(_d(a.amount)),
                "settlement_mode": str(a.settlement_mode)
                if getattr(a, "settlement_mode", None)
                else None,
                "status": _status_value(a.status),
                "created_at": a.created_at.isoformat()
                if getattr(a, "created_at", None)
                else None,
            }
            for a in successful_attempts
        ]

        # If an old/manual payment somehow has no attempts but persisted
        # total_paid is correct, still return a displayable payment line.
        if not payments_payload and total_paid > 0:
            payments_payload = [
                {
                    "method": str(intent.channel or "pos"),
                    "provider": None,
                    "amount": float(total_paid),
                    "settlement_mode": "manual",
                    "status": "succeeded",
                    "created_at": created_at,
                }
            ]

        # =====================================================
        # CANONICAL RECEIPT DTO
        # =====================================================

        return {
            "receipt_no": receipt_no,
            "tenant_name": ctx.get("tenant_name", "Company"),
            "branch_name": ctx.get("branch_name", ""),

            "customer": customer_payload,
            "description": description,
            "reference": reference,

            "created_at": created_at,
            "items": items,

            "gross_total": float(gross_total),
            "subtotal": float(gross_total),

            "client_total": float(net_due),
            "total": float(net_due),

            "tendered_total": float(tendered_total),
            "total_paid": float(total_paid),

            "balance_due": float(balance_due),
            "unpaid_amount": float(balance_due),

            "discount_total": float(discount_total),
            "complimentary_total": float(complimentary_total),

            "change_amount": float(change_amount),
            "change_given_now": float(safe_given),
            "change_remaining": float(change_remaining),
            "tip_amount": float(safe_tip),

            "payments": payments_payload,

            "payment_intent_id": str(intent.id),
            "payable_type": intent.payable_type,
            "payable_id": intent.payable_id,
            "status": _status_value(intent.status),
            "currency": intent.currency,

            "footer": meta.get(
                "footer",
                "Thank you! Come again to your Happy Home.",
            ),
            "powered_by": meta.get("powered_by", "XBOS"),
        }