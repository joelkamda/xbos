from fastapi import APIRouter, Request, Depends

from core.api.payments.receipts_controller import ReceiptsController
from core.rbac.utils.permission_decorator import require_permissions
from database import get_db

router = APIRouter(tags=["Receipts"])
controller = ReceiptsController()


@router.get("/receipts/{sale_id}")
@require_permissions("sale.view")
async def get_receipt(
    sale_id: int,
    request: Request,
    db=Depends(get_db),
):
    """
    Fetch printable receipt for a sale.

    Financial authority:
    - PaymentIntent.amount (NET due)
    - PaymentIntent.total_paid
    - PaymentIntent.balance_due
    """
    return await controller.get_receipt(
        request=request,
        sale_id=sale_id,
        db=db,
    )