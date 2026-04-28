from typing import Dict, Any, List

from fastapi import Request, HTTPException, status
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
            SalesController._sale_response(sale)
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

        return SalesController._sale_response(sale)

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

            return SalesController._sale_response(sale)

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
    def _sale_response(sale: Sale) -> Dict[str, Any]:

        return {
            "id": sale.id,
            "receipt_no": sale.receipt_no,
            "status": sale.status,
            "payment_method": sale.payment_method,
            "subtotal": float(sale.subtotal or 0),
            "total": float(sale.total or 0),
            "created_at": sale.created_at.isoformat(),
            "paid_at": sale.paid_at.isoformat() if sale.paid_at else None,

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