from typing import Dict, Any
from decimal import Decimal

from fastapi import Request, HTTPException, status
from sqlalchemy.orm import Session

from core.domain.sales.repository import SaleRepository
from core.domain.payments.repository import (
    PaymentIntentRepository,
    PaymentAttemptRepository,
)
from core.domain.payments.models import PaymentAttemptStatus


def _d(v: Any) -> Decimal:
    try:
        return Decimal(str(v))
    except Exception:
        return Decimal("0")


class ReceiptsController:
    """
    Receipt rendering controller (FINANCIAL AUTHORITY SAFE).

    Truth hierarchy:
    1. PaymentIntent.amount       → NET due (Client Pays)
    2. PaymentIntent.total_paid   → Tendered
    3. PaymentIntent.balance_due  → Unpaid / Store credit
    4. meta fields                → display extras only
    """

    async def get_receipt(
        self,
        *,
        request: Request,
        sale_id: int,
        db: Session,
    ) -> Dict[str, Any]:

        # -------------------------------------------------
        # Auth Context
        # -------------------------------------------------
        ctx = getattr(request.state, "user", None)
        if not ctx or not isinstance(ctx, dict):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing authentication context",
            )

        tenant_id = ctx["tenant_id"]
        branch_id = ctx["branch_id"]

        # -------------------------------------------------
        # Sale
        # -------------------------------------------------
        sale = SaleRepository.get_by_id(
            db,
            tenant_id=tenant_id,
            sale_id=sale_id,
        )

        if not sale or sale.branch_id != branch_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Sale not found",
            )

        # -------------------------------------------------
        # PaymentIntent (authoritative financial layer)
        # -------------------------------------------------
        intent = PaymentIntentRepository.get_by_payable(
            db,
            tenant_id=tenant_id,
            payable_type="sale",
            payable_id=sale.id,
        )

        if not intent:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="PaymentIntent not found for sale",
            )

        # -------------------------------------------------
        # Attempts
        # -------------------------------------------------
        attempts = PaymentAttemptRepository.list_for_intent(
            db,
            intent_id=intent.id,
        )

        successful_attempts = [
            a for a in attempts
            if a.status == PaymentAttemptStatus.succeeded
        ]

        # -------------------------------------------------
        # Intent financial truth
        # -------------------------------------------------
        net_due = _d(intent.amount)              # what client must pay
        total_paid = _d(intent.total_paid or 0)  # what was paid
        balance_due = _d(intent.balance_due or 0)

        unpaid_amount = balance_due if balance_due > 0 else Decimal("0")
        store_credit_amount = abs(balance_due) if balance_due < 0 else Decimal("0")

        # -------------------------------------------------
        # Meta (display-only enhancements)
        # -------------------------------------------------
        meta = intent.meta or {}

        gross_total = _d(meta.get("gross_total", sale.subtotal))
        discount_total = _d(meta.get("discount_total", 0))
        complimentary_total = _d(meta.get("complimentary_total", 0))

        tendered_meta = _d(meta.get("tendered_total", total_paid))
        change_meta = _d(meta.get("change_amount", store_credit_amount))

        unpaid_notes = meta.get("unpaid_notes", [])
        pos_note = meta.get("pos_note")

        # -------------------------------------------------
        # Payment breakdown
        # -------------------------------------------------
        payments_payload = [
            {
                "method": str(a.method),
                "provider": str(a.provider) if a.provider else None,
                "amount": float(_d(a.amount)),
            }
            for a in successful_attempts
        ]

        # -------------------------------------------------
        # Final Receipt Payload
        # -------------------------------------------------
        return {
            "receipt_no": sale.receipt_no,
            "tenant_name": ctx.get("tenant_name", "Company"),
            "branch_name": ctx.get("branch_name", f"Branch {branch_id}"),
            "created_at": sale.created_at.isoformat(),

            "items": [
                {
                    "name": item.name_snapshot,
                    "unit_price": float(_d(item.unit_price)),
                    "quantity": item.quantity,
                    "line_total": float(_d(item.line_total)),
                }
                for item in sale.items
            ],

            # -------------------------------------------------
            # Core Totals (correct semantics)
            # -------------------------------------------------
            "gross_total": float(gross_total),
            "subtotal": float(gross_total),

            # 🔥 Client Pays = NET due
            "client_total": float(net_due),
            "total": float(net_due),

            # 🔥 Paid
            "tendered_total": float(total_paid),
            "total_paid": float(total_paid),

            # 🔥 Unpaid / Credit
            "balance_due": float(balance_due),
            "unpaid_amount": float(unpaid_amount),
            "store_credit_amount": float(store_credit_amount),

            "has_outstanding_debt": unpaid_amount > 0,
            "has_store_credit": store_credit_amount > 0,

            # -------------------------------------------------
            # Discounts & Complimentary
            # -------------------------------------------------
            "discount_total": float(discount_total),
            "discount_reason": meta.get("discount_reason"),
            "complimentary_total": float(complimentary_total),
            "complimentary_items": meta.get("complimentary_items") or [],

            # -------------------------------------------------
            # POS Enhancements
            # -------------------------------------------------
            "change_amount": float(change_meta),
            "unpaid_notes": unpaid_notes,
            "pos_note": pos_note,

            # -------------------------------------------------
            # Payment breakdown
            # -------------------------------------------------
            "payments": payments_payload,

            "footer": "Thank you for your business",
            "powered_by": "XBOS",
        }