from fastapi import APIRouter, Request, Depends, HTTPException
from typing import Dict, Any
from sqlalchemy.orm import Session

from core.api.payments.payments_controller import PaymentsController
from core.domain.payments.service import PaymentService
from core.rbac.utils.permission_decorator import require_permissions
from database import get_db

router = APIRouter(tags=["Payments"])
controller = PaymentsController()


# -------------------------------------------------
# Initialize XafPay payment
# -------------------------------------------------

@router.post("/xafpay/init")
@require_permissions("payments.receive")
async def init_xafpay_payment(
    request: Request,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
):
    return await controller.init_xafpay_payment(
        request=request,
        payload=payload,
        db=db,
    )


# -------------------------------------------------
# POS Manual Settlement (Cash / Split / Unpaid)
# -------------------------------------------------

@router.post("/pos/settle")
@require_permissions("payments.receive")
async def pos_settle(
    request: Request,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
):
    ctx = getattr(request.state, "user", None)
    if not ctx or not isinstance(ctx, dict):
        raise HTTPException(status_code=401, detail="Missing authentication context")

    tenant_id = ctx["tenant_id"]
    branch_id = ctx["branch_id"]
    user_id = ctx["user_id"]

    sale_id = payload.get("sale_id")
    client_reference = payload.get("client_reference")
    lines = payload.get("lines") or []
    note = payload.get("note")

    if not sale_id or not client_reference:
        raise HTTPException(status_code=400, detail="sale_id and client_reference are required")

    intent = PaymentService.apply_pos_settlement(
        db,
        tenant_id=tenant_id,
        branch_id=branch_id,
        sale_id=int(sale_id),
        created_by_user_id=user_id,
        client_reference=str(client_reference),
        lines=lines,
        note=note,
    )

    db.commit()

    return {
        "status": "ok",
        "intent_id": intent.id,
        "total_paid": float(intent.total_paid or 0),
        "balance_due": float(intent.balance_due or 0),
    }