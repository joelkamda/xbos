from typing import Dict, Any

from fastapi import Request, HTTPException, status
from sqlalchemy.orm import Session

from core.domain.sales.repository import SaleRepository
from core.domain.payments.repository import PaymentRepository
from core.domain.payments.models import PaymentStatus
from core.domain.sales.models import SaleStatus


class ReceiptsController:
    """
    Receipt rendering controller.

    Responsibilities (LOCKED):
    - Tenant + branch safe fetch of Sale
    - Ensure Sale is PAID
    - Fetch successful Payments (supports split)
    - Assemble print-ready receipt payload
    - NO mutations
    """

    async def get_receipt(
        self,
        *,
        request: Request,
        sale_id: int,
        db: Session,
    ) -> Dict[str, Any]:

        # -------------------------------------------------
        # Auth context
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
        # Fetch Sale (tenant + branch safe)
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
        # Enforce PAID-only receipts
        # -------------------------------------------------
        if sale.status != SaleStatus.paid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Receipt available only for PAID sales",
            )

        # -------------------------------------------------
        # Fetch successful payments (split-ready)
        # -------------------------------------------------
        payments = PaymentRepository.get_for_sale(
            db,
            tenant_id=tenant_id,
            sale_id=sale.id,
        )

        successful_payments = [
            p for p in payments if p.status == PaymentStatus.paid
        ]

        # Defensive invariant: PAID sale must have PAID payments
        if not successful_payments:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Paid sale has no successful payments",
            )

        # -------------------------------------------------
        # Assemble receipt payload (UI-aligned)
        # -------------------------------------------------
        return {
            # -------------------------
            # Header
            # -------------------------
            "receipt_no": sale.receipt_no,
            "tenant_name": ctx.get("tenant_name", "Company"),
            "branch_name": ctx.get("branch_name", f"Branch {branch_id}"),
            "created_at": sale.created_at.isoformat(),

            # -------------------------
            # Items
            # -------------------------
            "items": [
                {
                    "name": item.name_snapshot,
                    "unit_price": float(item.unit_price),
                    "quantity": item.quantity,
                    "line_total": float(item.line_total),
                }
                for item in sale.items
            ],

            # -------------------------
            # Totals
            # -------------------------
            "subtotal": float(sale.subtotal),
            "total": float(sale.total),

            # -------------------------
            # Payments (split-safe)
            # -------------------------
            "payments": [
                {
                    "method": p.method,        # string
                    "provider": p.provider,    # string | None
                    "amount": float(p.amount),
                }
                for p in successful_payments
            ],

            # -------------------------
            # Footer
            # -------------------------
            "footer": "Thank you for your business",
            "powered_by": "XBOS",
        }
