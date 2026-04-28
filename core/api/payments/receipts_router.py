from fastapi import APIRouter, Request, Depends

from core.api.payments.receipts_controller import ReceiptsController
from core.rbac.utils.permission_decorator import require_permissions
from database import get_db

router = APIRouter(tags=["Receipts"])
controller = ReceiptsController()


# =========================================================
# SALE RECEIPT (EXISTING)
# =========================================================
@router.get("/receipts/{sale_id}")
@require_permissions("sale.view")
async def get_receipt(
    sale_id: int,
    request: Request,
    db=Depends(get_db),
):
    return await controller.get_receipt(
        request=request,
        sale_id=sale_id,
        db=db,
    )


# =========================================================
# 🔥 NEW: MANUAL / INTENT RECEIPT
# =========================================================
@router.get("/receipts/manual/{intent_id}")
@require_permissions("payments.view")
async def get_manual_receipt(
    intent_id: int,
    request: Request,
    db=Depends(get_db),
):
    """
    Fetch printable receipt for NON-SALE payments.

    Source of truth:
    - PaymentIntent ONLY (no Sale dependency)
    """
    return await controller.get_manual_receipt(
        request=request,
        intent_id=intent_id,
        db=db,
    )