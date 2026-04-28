from typing import Dict, Any
from decimal import Decimal

from fastapi import Request, HTTPException
from sqlalchemy.orm import Session

from core.domain.sales.repository import SaleRepository
from core.domain.payments.repository import (
    PaymentIntentRepository,
    PaymentAttemptRepository,
)
from core.domain.payments.models import PaymentAttemptStatus


def _d(v: Any) -> Decimal:
    try:
        if v is None:
            return Decimal("0")
        return Decimal(str(v))
    except Exception:
        return Decimal("0")


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
            raise HTTPException(status_code=500)

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
            raise HTTPException(404, "PaymentIntent not found")

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
            if a.status == PaymentAttemptStatus.succeeded
        ]

        net_due = _d(intent.amount)
        total_paid = _d(intent.total_paid or 0)
        balance_due = _d(intent.balance_due or 0)

        if balance_due < 0:
            balance_due = Decimal("0")

        meta = intent.meta or {}

        # 🔥 RAW VALUES
        change_amount = _d(meta.get("change_amount", 0))
        change_given_now = _d(meta.get("change_given_now", 0))
        tip_amount = _d(meta.get("tip_amount", 0))

        # 🔥 HARD BACKEND RECOMPUTE (FINAL SOURCE OF TRUTH)
        safe_given = min(change_given_now, change_amount)

        safe_tip = min(
            tip_amount,
            max(Decimal("0"), change_amount - safe_given)
        )

        change_remaining = max(
            Decimal("0"),
            change_amount - (safe_given + safe_tip)
        )

        # 🔥 WRITE BACK (ensures consistency everywhere)
        meta["change_given_now"] = float(safe_given)
        meta["tip_amount"] = float(safe_tip)
        meta["change_remaining"] = float(change_remaining)

        description = meta.get("description")
        reference = meta.get("reference")

        customer = meta.get("customer")
        if isinstance(customer, dict):
            customer_payload = {"name": customer.get("name")}
        elif isinstance(customer, str):
            customer_payload = {"name": customer}
        else:
            customer_payload = None

        gross_total = _d(meta.get("gross_total", net_due))
        discount_total = _d(meta.get("discount_total", 0))
        complimentary_total = _d(meta.get("complimentary_total", 0))

        tendered_total = _d(meta.get("tendered_total", total_paid))

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
            items = meta.get("items") or [
                {
                    "name": description or reference or "Payment",
                    "unit_price": float(net_due),
                    "quantity": 1,
                    "line_total": float(net_due),
                }
            ]

            receipt_no = f"MP-{intent.id}"
            created_at = intent.created_at.isoformat()

        payments_payload = [
            {
                "method": str(a.method),
                "provider": str(a.provider) if a.provider else None,
                "amount": float(_d(a.amount)),
            }
            for a in successful_attempts
        ]

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

            # 🔥 FINAL TRUSTED VALUES
            "change_amount": float(change_amount),
            "change_given_now": float(safe_given),
            "change_remaining": float(change_remaining),

            "tip_amount": float(safe_tip),

            "payments": payments_payload,

            "footer": "Thank you! Come again to your Happy Home.",
            "powered_by": "XBOS",
        }