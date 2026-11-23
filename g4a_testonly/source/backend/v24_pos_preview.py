"""TEST-only POS tender and 80mm preview; returns no PAID/settled proof.

Pure business calculation candidate: never talks to PSP, printer or ledger.
"""
from dataclasses import dataclass
from typing import Sequence
from uuid import UUID

TENDER_CHANNELS={"CASH","ORANGE","MTN","BANK","XAFPAY_TEST"}
@dataclass(frozen=True)
class Line:
    sku:str
    description:str
    quantity:int
    unit_price_xaf:int
    def validate(self):
        if not self.sku or not self.description or type(self.quantity)!=int or self.quantity<1:
            raise ValueError("LINE_INVALID")
        if type(self.unit_price_xaf)!=int or self.unit_price_xaf<0:
            raise ValueError("LINE_PRICE_INVALID")

@dataclass(frozen=True)
class Tender:
    channel:str
    amount_xaf:int
    state:str # CASH_RECEIVED_TEST / PROVIDER_PENDING_TEST / PROVIDER_CONFIRMED_TEST
    reference:str
    def validate(self):
        if self.channel not in TENDER_CHANNELS or type(self.amount_xaf)!=int or self.amount_xaf<1:
            raise ValueError("TENDER_INVALID")
        if self.state not in {"CASH_RECEIVED_TEST","PROVIDER_PENDING_TEST","PROVIDER_CONFIRMED_TEST"}:
            raise ValueError("TENDER_STATE_INVALID")
        if self.channel=="CASH" and self.state!="CASH_RECEIVED_TEST":
            raise ValueError("CASH_STATE_INVALID")
        if self.channel!="CASH" and self.state=="CASH_RECEIVED_TEST":
            raise ValueError("PROVIDER_STATE_INVALID")
        if not self.reference:
            raise ValueError("TENDER_REFERENCE_REQUIRED")

def preview(*,order_id:str,receipt_no:str,merchant:str,tax_id:str,
            lines:Sequence[Line],tenders:Sequence[Tender],discount_xaf:int=0,
            access:str="cashier",source_mode:str="TEST"):
    if source_mode!="TEST":raise PermissionError("LIVE_PAYMENT_PRINT_NOT_AUTHORIZED")
    if access not in {"cashier","admin"}:raise PermissionError("TEST_POS_ACCESS_DENIED")
    try: UUID(order_id)
    except ValueError as exc:raise ValueError("ORDER_UUID_INVALID") from exc
    if not merchant or not tax_id or not receipt_no:raise ValueError("LEGAL_RECEIPT_FIELDS_REQUIRED")
    if not lines:raise ValueError("EMPTY_ORDER")
    if type(discount_xaf)!=int or discount_xaf<0:raise ValueError("DISCOUNT_INVALID")
    for line in lines:line.validate()
    for tender in tenders:tender.validate()
    if len({(x.channel,x.reference) for x in tenders})!=len(tenders):
        raise ValueError("DUPLICATE_TENDER_REFERENCE")
    gross=sum(x.quantity*x.unit_price_xaf for x in lines)
    if discount_xaf>gross:raise ValueError("DISCOUNT_EXCEEDS_GROSS")
    total=gross-discount_xaf
    confirmed=sum(x.amount_xaf for x in tenders if x.state in {"CASH_RECEIVED_TEST","PROVIDER_CONFIRMED_TEST"})
    pending=sum(x.amount_xaf for x in tenders if x.state=="PROVIDER_PENDING_TEST")
    if confirmed+pending>total:raise ValueError("OVERPAYMENT_OR_PENDING_OVERALLOCATION")
    balance=total-confirmed
    # Confirmed provider TEST status is simulated, never real settlement evidence.
    status=("UNPAID_TEST" if confirmed==0 else "PARTIAL_TEST" if balance else "FULLY_ALLOCATED_TEST_NOT_PSP_PAID")
    width=42
    text_lines=[merchant[:width],f"NIU: {tax_id}"[:width],f"Receipt {receipt_no}"[:width],
                "PREVIEW ONLY — NOT A FISCAL RECEIPT","-"*width]
    for x in lines:
        text_lines.append(x.description[:width])
        text_lines.append(f" {x.quantity} x {x.unit_price_xaf:,} = {x.quantity*x.unit_price_xaf:,} XAF"[:width])
    text_lines.extend(["-"*width,f"GROSS: {gross:,} XAF",f"DISCOUNT: {discount_xaf:,} XAF",
                       f"TOTAL: {total:,} XAF",f"TEST ALLOCATED: {confirmed:,} XAF",
                       f"PENDING PROVIDER: {pending:,} XAF",f"OUTSTANDING: {balance:,} XAF",
                       "NO PHYSICAL PRINT / NO PSP CONFIRMATION"])
    return {"orderId":order_id,"receiptNo":receipt_no,"grossXaf":gross,
            "discountXaf":discount_xaf,"totalXaf":total,
            "confirmedTestXaf":confirmed,"providerPendingTestXaf":pending,
            "outstandingXaf":balance,"state":status,
            "realPspPaid":False,"printEffect":False,"financePosted":False,
            "width":width,"receiptPreview":"\n".join(text_lines)}
