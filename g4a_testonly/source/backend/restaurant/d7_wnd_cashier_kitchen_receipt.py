"""D7 W cashier/kitchen/80mm preview only; no real printer, order or PSP."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal
from restaurant.wnd_operational_policy import WND_POLICY

class WCashierDenied(ValueError):pass

@dataclass(frozen=True)
class CashierLine:
    sku:str
    name:str
    family:str
    qty:int
    unit_xaf:int
    stock_ref:str

@dataclass(frozen=True)
class CashierSource:
    tenant_id:int
    branch_id:int
    order_ref:str
    receipt_no:str
    cashier_ref:str
    staff_permission:bool
    kitchen_permission:bool
    lines:tuple[CashierLine,...]
    NIU:str
    mode:Literal["pending","unpaid","split"]="pending"
    provider_paid:bool=False
    source_only:bool=True
    real_authorized:bool=False

@dataclass(frozen=True)
class ReceiptKitchenPreview:
    receipt_lines:tuple[str,...]
    kitchen_skus:tuple[str,...]
    total_xaf:int
    order_ref:str
    receipt_no:str
    printed:bool=False
    kitchen_sent:bool=False
    order_persisted:bool=False
    marked_paid:bool=False
    can_print:bool=False
    effects:int=0
    source_only:bool=True

def preview_cashier(*,source:CashierSource,reprint:bool=False,
                    previously_printed:bool=False)->ReceiptKitchenPreview:
    if (not isinstance(source,CashierSource) or
            not all(type(x) is int and x>0 for x in (
                source.tenant_id,source.branch_id)) or
            source.source_only is not True or source.real_authorized is not False or
            not source.staff_permission or source.provider_paid is not False or
            not all(isinstance(x,str) and x.strip() for x in
                    (source.order_ref,source.receipt_no,source.cashier_ref,source.NIU)) or
            source.mode not in {"pending","unpaid","split"} or
            not isinstance(source.lines,tuple) or not source.lines):
        raise WCashierDenied("W_D7_CASHIER_SOURCE_UNTRUSTED")
    if reprint or previously_printed:
        raise WCashierDenied("W_D7_REPRINT_REQUIRES_REAL_AUTH_AND_OUTBOX")
    seen=set()
    total=0
    kitchen=[]
    printable=["WINE & DINE","NIU: "+source.NIU,"Receipt: "+source.receipt_no]
    for line in source.lines:
        if (not isinstance(line,CashierLine) or not line.sku or not line.stock_ref
                or not line.name or type(line.qty) is not int or line.qty<=0
                or type(line.unit_xaf) is not int or line.unit_xaf<0
                or line.sku in seen or line.family not in {"bar","kitchen","other"}):
            raise WCashierDenied("W_D7_CASHIER_INVALID_LINE")
        seen.add(line.sku)
        if line.family=="kitchen" and source.kitchen_permission:
            kitchen.append(line.sku)
        elif line.family=="kitchen":
            raise WCashierDenied("W_D7_KITCHEN_PERMISSION_MISSING")
        total+=line.qty*line.unit_xaf
        if total>10**12:raise WCashierDenied("W_D7_RECEIPT_TOTAL_TOO_LARGE")
        printable.extend((line.name[:32],f"{line.qty} x {line.unit_xaf} XAF"))
    printable.extend((f"TOTAL: {total} XAF","PREVIEW ONLY - NOT PAID",
                      "Thank you - Merci"))
    # Source labels are for a synthetic test; routing authority requires
    # a separately authenticated restaurant product classification lookup.
    return ReceiptKitchenPreview(tuple(printable),tuple(kitchen),
                                 total,source.order_ref,source.receipt_no)

def print_or_mark_paid(*_args,**_kwargs):
    raise WCashierDenied("W_D7_PHYSICAL_PRINT_AND_PAID_NOT_ADMITTED")
