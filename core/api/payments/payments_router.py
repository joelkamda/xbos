from fastapi import APIRouter, Request, Depends
from typing import Dict, Any
from sqlalchemy.orm import Session

from core.api.payments.payments_controller import PaymentsController
from core.api.accounting.accounting_router import ManualIncomePayload, ExpensePayload, CashMovementPayload, _normalize_payload_dates, _list_accounts_receivable_for_context, _get_accounts_receivable_for_context
from core.rbac.utils.permission_decorator import require_permissions
from database import get_db

router = APIRouter(tags=["Payments"])
controller = PaymentsController()


# -------------------------------------------------
# List payments (for Payments dashboard)
# -------------------------------------------------

@router.get("/")
@require_permissions("payments.view")
async def list_payments(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Return recent payments for the Payments dashboard.

    Supports tenant + branch isolation through request context.
    """
    return await controller.list_payments(
        request=request,
        db=db,
    )


# -------------------------------------------------
# Unified Payments activity projection
# -------------------------------------------------

@router.get("/activity")
@require_permissions("payments.view")
async def payments_activity(
    request: Request,
    db: Session = Depends(get_db),
    limit: int = 100,
):
    return await controller.list_activity(
        request=request,
        db=db,
        limit=limit,
    )


# -------------------------------------------------
# Get single payment
# -------------------------------------------------

@router.get("/{payment_id}")
@require_permissions("payments.view")
async def get_payment(
    payment_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Return a single payment with attempts and settlement info.
    """
    return await controller.get_payment(
        payment_id=payment_id,
        request=request,
        db=db,
    )


# -------------------------------------------------
# XafPay payment initialization
# -------------------------------------------------

@router.post("/xafpay/init")
@require_permissions("payments.receive")
async def init_xafpay_payment(
    request: Request,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
):
    """
    Start XafPay payment flow.

    Creates or reuses a PaymentIntent
    and returns a gateway checkout URL.
    """
    return await controller.init_xafpay_payment(
        request=request,
        payload=payload,
        db=db,
    )


# -------------------------------------------------
# Standalone Income Taxonomy
# -------------------------------------------------

@router.get("/standalone/income-taxonomy")
@require_permissions("payments.receive")
async def standalone_income_taxonomy(
    request: Request,
    db: Session = Depends(get_db),
):
    """Canonical Revenue taxonomy for Payments receive operations."""
    return await controller.standalone_income_taxonomy(
        request=request,
        db=db,
    )


# -------------------------------------------------
# Standalone Expense Taxonomy
# -------------------------------------------------

@router.get("/standalone/expense-taxonomy")
@require_permissions("payments.send")
async def standalone_expense_taxonomy(
    request: Request,
    db: Session = Depends(get_db),
):
    """Canonical Expenses taxonomy for Payments pay operations."""
    return await controller.standalone_expense_taxonomy(
        request=request,
        db=db,
    )


# -------------------------------------------------
# Standalone Receivables
# -------------------------------------------------

@router.get("/standalone/receivables")
@require_permissions("payments.receive")
def standalone_receivables(
    request: Request,
    db: Session = Depends(get_db),
    limit: int = 200,
    offset: int = 0,
):
    """Canonical branch-scoped A/R discovery for Payments receive operations."""
    return _list_accounts_receivable_for_context(
        request=request,
        db=db,
        limit=limit,
        offset=offset,
    )


# -------------------------------------------------
# Standalone Receivable Resolver
# -------------------------------------------------

def _standalone_receivables_search_for_context(
    *,
    request: Request,
    db: Session,
    q: str = "",
    limit: int = 25,
):
    # Complete read-only resolver over canonical branch-scoped open A/R.
    # Search intentionally ignores repayment-history text so a bill number
    # does not produce unrelated receivables from nested repayment metadata.
    safe_limit = max(1, min(int(limit or 25), 100))
    raw_query = str(q or "").strip().lower()

    if not raw_query:
        page = _list_accounts_receivable_for_context(
            request=request,
            db=db,
            limit=safe_limit,
            offset=0,
        )
        items = page.get("items") or []
        return {
            "query": "",
            "count": len(items),
            "items": items,
        }

    query = raw_query
    for prefix in (
        "sale #",
        "sale ",
        "bill #",
        "bill ",
        "a/r #",
        "ar #",
        "a/r ",
        "ar ",
    ):
        if query.startswith(prefix):
            query = query[len(prefix):].strip()
            break
    query = query.lstrip("#").strip() or raw_query

    ranked = []
    page_size = 200
    offset = 0
    sequence = 0

    def _text(value):
        return str(value or "").strip().lower()

    def _score(item):
        ar_id = _text(item.get("id"))
        sale_id = _text(item.get("sale_id"))

        if sale_id == query:
            return 1000
        if ar_id == query:
            return 950

        customer = item.get("customer")
        customer = customer if isinstance(customer, dict) else {}
        sale = item.get("sale")
        sale = sale if isinstance(sale, dict) else {}
        meta = item.get("meta")
        meta = meta if isinstance(meta, dict) else {}

        phones = [
            item.get("customer_phone"),
            item.get("phone"),
            customer.get("phone"),
            customer.get("mobile"),
        ]
        names = [
            item.get("customer_name"),
            item.get("party_name"),
            item.get("account_name"),
            customer.get("name"),
            customer.get("full_name"),
        ]
        references = [
            item.get("reference"),
            item.get("receipt_no"),
            item.get("bill_no"),
            item.get("invoice_no"),
            sale.get("receipt_no"),
            sale.get("reference"),
            meta.get("reference"),
            meta.get("receipt_no"),
            meta.get("bill_no"),
        ]

        if any(query == _text(value) for value in phones if value is not None):
            return 900
        if any(query in _text(value) for value in phones if value is not None):
            return 850
        if any(query == _text(value) for value in references if value is not None):
            return 800
        if any(query in _text(value) for value in names if value is not None):
            return 700
        if any(query in _text(value) for value in references if value is not None):
            return 650

        identifiers = [ar_id, sale_id, _text(sale.get("id"))]
        if any(query in value for value in identifiers if value):
            return 500

        return 0

    while True:
        page = _list_accounts_receivable_for_context(
            request=request,
            db=db,
            limit=page_size,
            offset=offset,
        )
        items = page.get("items") or []

        for item in items:
            score = _score(item)
            if score:
                ranked.append((score, sequence, item))
            sequence += 1

        if len(items) < page_size:
            break

        offset += page_size

    ranked.sort(key=lambda row: (-row[0], row[1]))
    matches = [row[2] for row in ranked[:safe_limit]]

    return {
        "query": raw_query,
        "count": len(matches),
        "items": matches,
    }


@router.get("/standalone/receivables/search")
@require_permissions("payments.receive")
def standalone_receivables_search(
    request: Request,
    db: Session = Depends(get_db),
    q: str = "",
    limit: int = 25,
):
    return _standalone_receivables_search_for_context(
        request=request,
        db=db,
        q=q,
        limit=limit,
    )


# -------------------------------------------------
# Standalone Receivable Detail
# -------------------------------------------------

@router.get("/standalone/receivables/{ar_id}")
@require_permissions("payments.receive")
def standalone_receivable_detail(
    ar_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Canonical branch-scoped A/R detail for Payments receive operations."""
    return _get_accounts_receivable_for_context(
        ar_id=ar_id,
        request=request,
        db=db,
    )


# -------------------------------------------------
# Standalone Receive Income
# -------------------------------------------------

@router.post("/standalone/receive-income")
@require_permissions("payments.receive")
async def standalone_receive_income(
    payload: ManualIncomePayload,
    request: Request,
    db: Session = Depends(get_db),
):
    """Payments facade over canonical manual-income accounting authority."""
    return await controller.standalone_receive_income(
        request=request,
        payload=_normalize_payload_dates(payload.model_dump()),
        db=db,
    )


# -------------------------------------------------
# Standalone Pay Expense
# -------------------------------------------------

@router.post("/standalone/pay-expense")
@require_permissions("payments.send")
async def standalone_pay_expense(
    payload: ExpensePayload,
    request: Request,
    db: Session = Depends(get_db),
):
    """Payments facade over canonical expense accounting authority."""
    return await controller.standalone_pay_expense(
        request=request,
        payload=_normalize_payload_dates(payload.model_dump()),
        db=db,
    )


# -------------------------------------------------
# Standalone Transfer
# -------------------------------------------------

@router.post("/standalone/transfer")
@require_permissions("payments.send")
async def standalone_transfer(
    payload: CashMovementPayload,
    request: Request,
    db: Session = Depends(get_db),
):
    """Payments facade over canonical cash-movement authority."""
    return await controller.standalone_transfer(
        request=request,
        payload=_normalize_payload_dates(payload.model_dump()),
        db=db,
    )


# -------------------------------------------------
# POS Settlement (Cash / MTN / Orange / Split / Unpaid)
# -------------------------------------------------

@router.post("/pos/settle")
@require_permissions("payments.receive")
async def pos_settle(
    request: Request,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
):
    """
    Manual POS settlement.

    Delegates all financial logic to PaymentService
    through the controller.
    """
    return await controller.pos_settle(
        request=request,
        payload=payload,
        db=db,
    )