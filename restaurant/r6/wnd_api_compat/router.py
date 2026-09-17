
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from core.rbac.utils.permission_decorator import require_permissions
from core.api.accounting.accounting_router import (
    ManualIncomePayload, ExpensePayload, CashMovementPayload, _normalize_payload_dates,
)
from core.api.inventory.inventory_controller import InventoryController

from .payments_controller import PaymentsController
from .orders_controller import OrdersController
from .operational_reports_service import OperationalReportsService
from .stock_report_service import StockReportService
from .stock_reconciliation_service import StockReconciliationService
from .inventory_service import InventoryService
from . import ar_compat
from .customers_router import router as customers_router

router = APIRouter(prefix="/kernel", tags=["WND R6 Compatibility"])
router.include_router(customers_router, prefix="/customers")

payments = PaymentsController()
orders = OrdersController()
inventory_controller = InventoryController()


def _wnd_ctx(request: Request):
    ctx = getattr(request.state, "user", None)
    if not ctx or not isinstance(ctx, dict):
        raise HTTPException(status_code=401, detail="Missing auth context")
    if int(ctx.get("tenant_id") or 0) != 2:
        raise HTTPException(status_code=404, detail="Compatibility route not available")
    return ctx


class AccountsReceivableIdentityPayload(BaseModel):
    customer_name: str = Field(..., min_length=1, max_length=200)
    customer_phone: str | None = Field(default=None, max_length=80)
    customer_id: int | None = None


@router.get("/orders/sale-fulfillment-modes")
@require_permissions("sale.view")
def sale_fulfillment_modes(request: Request, limit: int = Query(200, ge=1, le=500), db: Session = Depends(get_db)):
    ctx = _wnd_ctx(request)
    rows = db.execute(__import__('sqlalchemy').text("""
        SELECT s.id AS sale_id, o.fulfillment_mode
        FROM sales s LEFT JOIN orders o ON o.id=s.order_id
        WHERE s.tenant_id=:t AND s.branch_id=:b
        ORDER BY s.created_at DESC NULLS LAST, s.id DESC LIMIT :limit
    """), {"t": int(ctx["tenant_id"]), "b": int(ctx["branch_id"]), "limit": int(limit)}).mappings().all()
    return {
        "modes_by_sale_id": {str(int(r["sale_id"])): r["fulfillment_mode"] for r in rows},
        "tracked_values": ["DINE_IN", "TAKEAWAY", "DELIVERY"],
        "historical_null_means": "UNSPECIFIED",
    }


@router.get("/orders/kitchen/history")
@require_permissions("order.view")
async def kitchen_history(request: Request, start: str = Query(...), end: str = Query(...), limit: int = Query(500, ge=1, le=2000)):
    _wnd_ctx(request)
    return await orders.kitchen_history(request, start=start, end=end, limit=limit)


@router.get("/orders/kitchen/item-summary")
@require_permissions("order.view")
async def kitchen_item_summary(request: Request, start: str = Query(...), end: str = Query(...), db: Session = Depends(get_db)):
    _wnd_ctx(request)
    return await orders.kitchen_item_summary(request, start=start, end=end, db=db)


@router.get("/payments/activity")
@require_permissions("payments.view")
async def payments_activity(request: Request, db: Session = Depends(get_db), limit: int = 100):
    _wnd_ctx(request)
    return await payments.list_activity(request=request, db=db, limit=limit)


@router.get("/payments/standalone/income-taxonomy")
@require_permissions("payments.receive")
async def standalone_income_taxonomy(request: Request, db: Session = Depends(get_db)):
    _wnd_ctx(request)
    return await payments.standalone_income_taxonomy(request=request, db=db)


@router.get("/payments/standalone/expense-taxonomy")
@require_permissions("payments.send")
async def standalone_expense_taxonomy(request: Request, db: Session = Depends(get_db)):
    _wnd_ctx(request)
    return await payments.standalone_expense_taxonomy(request=request, db=db)


@router.get("/payments/standalone/receivables")
@require_permissions("payments.receive", "accounting.view")
def standalone_receivables(request: Request, db: Session = Depends(get_db), limit: int = 200, offset: int = 0):
    return ar_compat.list_accounts(request=request, db=db, limit=limit, offset=offset)


@router.get("/payments/standalone/receivables/search")
@require_permissions("payments.receive", "accounting.view")
def standalone_receivables_search(request: Request, db: Session = Depends(get_db), q: str = "", limit: int = 25):
    return ar_compat.search_accounts(request=request, db=db, q=q, limit=limit)


@router.get("/payments/standalone/receivables/{ar_id}")
@require_permissions("payments.receive", "accounting.view")
def standalone_receivable_detail(ar_id: int, request: Request, db: Session = Depends(get_db)):
    return ar_compat.get_account(ar_id, request, db)


@router.post("/payments/standalone/receive-income")
@require_permissions("payments.receive", "accounting.post")
async def standalone_receive_income(payload: ManualIncomePayload, request: Request, db: Session = Depends(get_db)):
    _wnd_ctx(request)
    return await payments.standalone_receive_income(request=request, payload=_normalize_payload_dates(payload.model_dump()), db=db)


@router.post("/payments/standalone/pay-expense")
@require_permissions("payments.send", "accounting.post")
async def standalone_pay_expense(payload: ExpensePayload, request: Request, db: Session = Depends(get_db)):
    _wnd_ctx(request)
    return await payments.standalone_pay_expense(request=request, payload=_normalize_payload_dates(payload.model_dump()), db=db)


@router.post("/payments/standalone/transfer")
@require_permissions("payments.send", "accounting.post")
async def standalone_transfer(payload: CashMovementPayload, request: Request, db: Session = Depends(get_db)):
    _wnd_ctx(request)
    return await payments.standalone_transfer(request=request, payload=_normalize_payload_dates(payload.model_dump()), db=db)


@router.patch("/accounting/accounts/ar/{ar_id}/identity")
@require_permissions("accounting.post")
def update_ar_identity(ar_id: int, payload: AccountsReceivableIdentityPayload, request: Request, db: Session = Depends(get_db)):
    return ar_compat.update_identity(
        ar_id=ar_id, customer_name=payload.customer_name, customer_phone=payload.customer_phone,
        customer_id=payload.customer_id, request=request, db=db,
    )


@router.get("/inventory/reconciliation")
@require_permissions("inventory.reconcile")
def get_inventory_reconciliation(request: Request, business_date: str, shift: str = "day", db: Session = Depends(get_db)):
    ctx = _wnd_ctx(request)
    try:
        return StockReconciliationService.get_window(db, tenant_id=int(ctx["tenant_id"]), branch_id=int(ctx["branch_id"]), business_date=business_date, shift=shift)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/inventory/reconciliation/close")
@require_permissions("inventory.reconcile")
def close_inventory_reconciliation(request: Request, payload: dict = Body(...), db: Session = Depends(get_db)):
    ctx = _wnd_ctx(request)
    try:
        result = StockReconciliationService.close_window(
            db, tenant_id=int(ctx["tenant_id"]), branch_id=int(ctx["branch_id"]),
            business_date=str(payload.get("business_date") or ""), shift=str(payload.get("shift") or "day"),
            lines=payload.get("lines") or [], note=str(payload.get("note") or ""),
            closed_by_user_id=(ctx.get("id") or ctx.get("user_id")),
        )
        db.commit(); return result
    except ValueError as exc:
        db.rollback(); detail = str(exc)
        raise HTTPException(status_code=409 if "already closed" in detail.lower() else 400, detail=detail)
    except Exception:
        db.rollback(); raise


@router.post("/inventory/waste")
@require_permissions("inventory.consume")
def record_inventory_waste(request: Request, payload: dict = Body(...), db: Session = Depends(get_db)):
    ctx = _wnd_ctx(request)
    atomic_unit_id = inventory_controller._int_payload(payload, "atomic_unit_id")
    quantity = inventory_controller._int_payload(payload, "quantity")
    reference_id = payload.get("reference_id")
    reference_id = int(reference_id) if reference_id not in (None, "") else None
    movement_type = str(payload.get("movement_type") or "waste").strip().lower()
    try:
        movement = InventoryService.record_waste_or_loss(
            db, tenant_id=int(ctx["tenant_id"]), branch_id=int(ctx["branch_id"]),
            atomic_unit_id=atomic_unit_id, quantity=quantity, movement_type=movement_type,
            source=payload.get("source") or "manual", reference_type=payload.get("reference_type") or movement_type,
            reference_id=reference_id, allow_negative=inventory_controller._bool_payload(payload, "allow_negative", default=False),
        )
        db.commit(); db.refresh(movement)
        return {
            "ok": True,
            "movement": inventory_controller._serialize_movement(movement),
            "stock_status": InventoryService.get_stock_status(
                db, tenant_id=int(ctx["tenant_id"]), branch_id=int(ctx["branch_id"]), atomic_unit_id=atomic_unit_id,
            ),
        }
    except ValueError as exc:
        db.rollback(); raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        db.rollback(); raise


_REPORT_PERMS = ("report.view", "report.financial", "report.finance.view", "report.financial.overview")

@router.get("/reports/payments")
@require_permissions(*_REPORT_PERMS)
def payments_report(month: str, request: Request, db: Session = Depends(get_db)):
    ctx = _wnd_ctx(request)
    try:
        return OperationalReportsService.payment_report(db, tenant_id=int(ctx["tenant_id"]), branch_id=int(ctx["branch_id"]), month=month)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@router.get("/reports/reconciliation")
@require_permissions(*_REPORT_PERMS)
def reconciliation_report(month: str, request: Request, db: Session = Depends(get_db)):
    ctx = _wnd_ctx(request)
    try:
        return OperationalReportsService.reconciliation_report(db, tenant_id=int(ctx["tenant_id"]), branch_id=int(ctx["branch_id"]), month=month)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@router.get("/reports/stock")
@require_permissions(*_REPORT_PERMS)
def stock_report(start: str, end: str, request: Request, db: Session = Depends(get_db)):
    ctx = _wnd_ctx(request)
    try:
        return StockReportService.report(db, tenant_id=int(ctx["tenant_id"]), branch_id=int(ctx["branch_id"]), start_date=start, end_date=end)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@router.get("/reports/debt")
@require_permissions(*_REPORT_PERMS)
def debt_report(request: Request, db: Session = Depends(get_db)):
    ctx = _wnd_ctx(request)
    return OperationalReportsService.debt_report(db, tenant_id=int(ctx["tenant_id"]), branch_id=int(ctx["branch_id"]))
