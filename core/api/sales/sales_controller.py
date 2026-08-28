from typing import Dict, Any, List

from fastapi import Request, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from core.domain.sales.service import SaleService
from core.domain.sales.repository import SaleRepository
from core.domain.sales.models import Sale
from core.errors.api_error import APIError


class SalesController:
    """
    HTTP controller for Sales.

    Responsibilities (LOCKED):
    - Extract request context (tenant, branch, user)
    - Call SaleService
    - Return canonical, payment-free Sale response
    """

    # -------------------------------------------------
    # GET /sales
    # -------------------------------------------------

    @staticmethod
    async def list_sales(
        request: Request,
        db: Session,
    ) -> List[Dict[str, Any]]:

        ctx = getattr(request.state, "user", None)

        if not ctx or not isinstance(ctx, dict):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing authentication context",
            )

        # ✅ Extract optional filters (important for pending screen)
        status_filter = request.query_params.get("status")

        sales = SaleService.list_sales(
            db,
            tenant_id=ctx["tenant_id"],
            branch_id=ctx["branch_id"],
            status=status_filter,  # 👈 PASS FILTER DOWN
        )

        # -------------------------------------------------
        # 🔥 CRITICAL FIX: DEDUPE AT CONTROLLER LEVEL
        # -------------------------------------------------

        unique_map: Dict[int, Sale] = {}

        for sale in sales:
            if sale.id not in unique_map:
                unique_map[sale.id] = sale

        unique_sales = list(unique_map.values())

        return [
            SalesController._sale_response(sale, db)
            for sale in unique_sales
        ]

    # -------------------------------------------------
    # GET /sales/{id}
    # -------------------------------------------------

    @staticmethod
    async def get_sale(
        request: Request,
        sale_id: int,
        db: Session,
    ) -> Dict[str, Any]:

        ctx = getattr(request.state, "user", None)

        if not ctx or not isinstance(ctx, dict):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing authentication context",
            )

        sale = SaleRepository.get_by_id(
            db,
            tenant_id=ctx["tenant_id"],
            sale_id=sale_id,
        )

        if not sale:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Sale not found",
            )

        return SalesController._sale_response(sale, db)

    # -------------------------------------------------
    # POST /sales
    # -------------------------------------------------

    @staticmethod
    async def create_sale(
        request: Request,
        payload: Dict[str, Any],
        db: Session,
    ) -> Dict[str, Any]:

        ctx = getattr(request.state, "user", None)

        if not ctx or not isinstance(ctx, dict):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing authentication context",
            )

        try:
            sale: Sale = SaleService.create_sale(
                db,
                tenant_id=ctx["tenant_id"],
                branch_id=ctx["branch_id"],
                cashier_id=ctx["user_id"],
                payload=payload,
            )

            return SalesController._sale_response(sale, db)

        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

        except Exception as e:
            raise APIError(f"Failed to create sale: {str(e)}") from e

    # -------------------------------------------------
    # Response helpers
    # -------------------------------------------------

    @staticmethod
    def _sale_response(sale: Sale, db: Session) -> Dict[str, Any]:

        projection = db.execute(text("""
            SELECT amount,total_paid,balance_due,status
              FROM payment_intents
             WHERE tenant_id=:tenant AND payable_type='sale' AND payable_id=:sale
             ORDER BY id DESC LIMIT 1
        """), {"tenant": sale.tenant_id, "sale": sale.id}).mappings().one_or_none()
        total = float((projection or {}).get("amount") or sale.total or 0)
        confirmed_local = db.execute(text("""
            SELECT amount
              FROM payment_attempts
             WHERE payment_intent_id=(SELECT id FROM payment_intents
                                       WHERE tenant_id=:tenant AND payable_type='sale'
                                         AND payable_id=:sale ORDER BY id DESC LIMIT 1)
               AND lower(status) IN ('succeeded','success','completed','complete','paid')
               AND lower(coalesce(method,'')) <> 'xafpay'
             ORDER BY created_at,id
        """), {"tenant": sale.tenant_id, "sale": sale.id}).scalars().all()
        paid = 0.0
        for confirmed_amount in confirmed_local:
            amount = float(confirmed_amount or 0)
            # A confirmed local leg may satisfy only the then-current balance.
            # Ignore malformed/duplicate rows that exceed it; do not let a stale
            # PaymentIntent summary manufacture a fully-paid archive state.
            if amount > 0 and amount <= total - paid:
                paid += amount
        canonical = db.execute(text("""
            SELECT a.attempt_state,a.attempted_amount,a.payment_rail_code,
                   EXISTS(SELECT 1 FROM payment_settlements s
                           WHERE s.tenant_id=a.tenant_id AND s.payment_attempt_id=a.id
                             AND s.settlement_state='confirmed') settled
              FROM canonical_payment_attempts a
             WHERE a.tenant_id=:tenant AND a.metadata->>'sale_id'=:sale
               AND a.orchestrator_code='xafpay'
             ORDER BY a.occurred_at DESC,a.id DESC LIMIT 1
        """), {"tenant": sale.tenant_id, "sale": str(sale.id)}).mappings().one_or_none()
        confirmed_xafpay = db.execute(text("""
            SELECT coalesce(sum(s.gross_amount),0)
              FROM payment_settlements s
              JOIN canonical_payment_attempts a
                ON a.tenant_id=s.tenant_id AND a.id=s.payment_attempt_id
             WHERE s.tenant_id=:tenant AND a.metadata->>'sale_id'=:sale
               AND a.orchestrator_code='xafpay'
               AND s.settlement_state IN ('confirmed','partially_reversed')
        """), {"tenant": sale.tenant_id, "sale": str(sale.id)}).scalar_one()
        paid = min(total, paid + float(confirmed_xafpay or 0))
        due = max(0.0, total - paid)
        attempt_state = str((canonical or {}).get("attempt_state") or "").upper() or None
        ar = db.execute(text("""
            SELECT coalesce(sum(balance_due),0) FROM accounts_receivable
             WHERE tenant_id=:tenant AND sale_id=:sale AND status IN ('open','partial')
        """), {"tenant": sale.tenant_id, "sale": sale.id}).scalar_one()
        if due <= 0:
            payment_state = "PAID"
        elif float(ar or 0) > 0:
            payment_state = "RECEIVABLE"
        elif attempt_state in {"PENDING", "PROCESSING", "UNKNOWN"}:
            payment_state = "PAYMENT_PENDING"
        elif paid > 0:
            payment_state = "PARTIAL"
        else:
            payment_state = "UNPAID"

        return {
            "id": sale.id,
            "receipt_no": sale.receipt_no,
            "status": sale.status,
            "payment_method": sale.payment_method,
            "subtotal": float(sale.subtotal or 0),
            "total": float(sale.total or 0),
            "created_at": sale.created_at.isoformat(),
            "paid_at": sale.paid_at.isoformat() if sale.paid_at else None,
            "paid_amount": paid,
            "unpaid_amount": due,
            "payment_state": payment_state,
            "payment_summary": {
                "commercial_total": total,
                "total_paid": paid,
                "balance_due": due,
                "approved_ar": float(ar or 0),
                "collectible_now": max(0.0, due - float(ar or 0)),
                "latest_xafpay_attempt_state": attempt_state,
                "latest_xafpay_rail": (canonical or {}).get("payment_rail_code"),
                "latest_xafpay_settled": bool((canonical or {}).get("settled")),
            },

            # ✅ SAFE ITEMS HANDLING
            "items": [
                {
                    "atomic_unit_id": item.atomic_unit_id,
                    "name": item.name_snapshot,
                    "unit_price": float(item.unit_price or 0),
                    "quantity": item.quantity,
                    "line_total": float(item.line_total or 0),
                }
                for item in (sale.items or [])
            ],
        }
