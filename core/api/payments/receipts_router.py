from fastapi import APIRouter, Request, Depends

from core.api.payments.receipts_controller import ReceiptsController
from core.rbac.utils.permission_decorator import require_permissions
from database import get_db

router = APIRouter()
controller = ReceiptsController()


@router.get("/receipts/{sale_id}")
@require_permissions("sale.view")
async def get_receipt(
    sale_id: int,
    request: Request,
    db = Depends(get_db),
):
    """
    Fetch a printable receipt for a PAID sale.
    """
    return await controller.get_receipt(
        request=request,
        sale_id=sale_id,
        db=db,
    )
