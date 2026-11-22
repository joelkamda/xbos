"""WND V24 W cashier shift handoff PREVIEW — synthetic TEST only.

Uses the existing native PostgreSQL R4 daily/shift statement and ONLY
server-side recorded CASH_RECEIVED_TEST tender intentions as cash evidence.
Manual finance drafts, provider-pending intentions, discounts and receivable
markers are displayed separately, never silently reclassified as cash.

No official settlement, reconciliation close, signed receipt reprint,
printer, PSP, protected WND data, or production posting is possible.
Current native R4 daily readback is permitted to merchant/reviewer/closer
TEST actors; CASHIER_TEST access is explicitly not claimed yet.
"""
from __future__ import annotations

from datetime import date
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, StrictInt, ConfigDict
from .api import auth, TENANT, BRANCH
from .v24_native_api import actor_role
from .v24_r4_readmodels import daily, windows

handoff_router=APIRouter(
    prefix="/api/v3/v24/w",tags=["bounded-w-restaurant-shift-test"]
)
DENOMS={10000,5000,2000,1000,500,100,50,25}
MAX_XAF=10**12

class ShiftHandoffPreview(BaseModel):
    model_config=ConfigDict(extra="forbid")
    business_day:date
    shift:Literal["DAY","NIGHT"]
    opening_cash_xaf:StrictInt=Field(ge=0,le=MAX_XAF)
    physically_counted_cash_xaf:StrictInt=Field(ge=0,le=MAX_XAF)
    piece_counts:dict[str,StrictInt]|None=None
    discrepancy_note:str|None=Field(default=None,max_length=400)

def deny(code:str,status=422):
    raise HTTPException(status_code=status,detail=code)

def safe_money(value, field:str, negative:bool=False)->int:
    if type(value) is not int or abs(value)>MAX_XAF or (not negative and value<0):
        deny("W_SHIFT_UNTRUSTED_NATIVE_"+field)
    return value

def validate_note_counts(counts:dict[str,int]|None,actual:int):
    if counts is None:return None
    if not counts:deny("W_SHIFT_EMPTY_DENOMINATIONS")
    summed=0
    for den,count in counts.items():
        if den not in {str(x) for x in DENOMS} or type(count) is not int or count<0 or count>10**6:
            deny("W_SHIFT_INVALID_DENOMINATION")
        summed+=int(den)*count
        if summed>MAX_XAF:deny("W_SHIFT_COUNT_OVERFLOW")
    if summed!=actual:
        deny("W_SHIFT_PHYSICAL_NOTE_COUNT_MISMATCH")
    return summed

def from_native_daily(body:ShiftHandoffPreview,raw:dict)->dict:
    """Fail closed on ambiguous native source fields; no finance side effects."""
    if (not isinstance(raw,dict) or
        raw.get("grade")!="SYNTHETIC_TEST_ONLY_NO_CANONICAL_ACCOUNTING" or
        raw.get("day")!=body.business_day.isoformat() or
        raw.get("shift")!=body.shift or
        raw.get("scope")!={"tenant":TENANT,"branch":BRANCH}):
        deny("W_SHIFT_NATIVE_SOURCE_OR_SCOPE_MISMATCH",409)
    start,end=windows(body.business_day,body.shift)
    if (raw.get("start")!=start.astimezone(__import__("datetime").timezone.utc).isoformat()
        or raw.get("endExclusive")!=end.astimezone(__import__("datetime").timezone.utc).isoformat()):
        deny("W_SHIFT_TIME_WINDOW_MISMATCH",409)
    s=raw.get("sales")
    if not isinstance(s,dict):deny("W_SHIFT_SALES_SOURCE_MISSING",409)
    gross=safe_money(s.get("grossXaf"),"GROSS")
    discount=safe_money(s.get("discountXaf"),"DISCOUNT")
    net=safe_money(s.get("netDueXaf"),"NET_DUE")
    if discount>gross or net!=gross-discount:
        deny("W_SHIFT_DISCOUNT_NET_MISMATCH",409)
    if type(s.get("count")) is not int or s["count"]<0:
        deny("W_SHIFT_INVALID_SALE_COUNT",409)

    cash=0
    provider_pending=0
    other_tender=[]
    tenders=raw.get("tenderEvents")
    if not isinstance(tenders,list):deny("W_SHIFT_TENDER_SOURCE_MISSING",409)
    for tender in tenders:
        if not isinstance(tender,dict):deny("W_SHIFT_TENDER_SOURCE_INVALID",409)
        amount=safe_money(tender.get("amount"),"TENDER")
        channel,status=tender.get("channel"),tender.get("status")
        if not isinstance(channel,str) or not isinstance(status,str):
            deny("W_SHIFT_TENDER_CLASSIFICATION_UNKNOWN",409)
        if channel=="CASH" and status=="CASH_RECEIVED_TEST":
            cash+=amount
        elif channel!="CASH" and status=="PROVIDER_PENDING_TEST":
            provider_pending+=amount
        else:
            # Do NOT imply CASH/other channel has settled when event unclear.
            other_tender.append({"channel":channel,"status":status,"amountXaf":amount})
        if cash>MAX_XAF or provider_pending>MAX_XAF:deny("W_SHIFT_TENDER_SUM_OVERFLOW")

    manual=raw.get("manualFinanceDraftEvents")
    if not isinstance(manual,list):deny("W_SHIFT_FINANCE_SOURCE_MISSING",409)
    manual_cash_draft=0
    manual_unclassified=[]
    for entry in manual:
        if not isinstance(entry,dict):deny("W_SHIFT_FINANCE_SOURCE_INVALID",409)
        value=safe_money(entry.get("amount"),"MANUAL_DRAFT",negative=True)
        kind,channel=entry.get("kind"),entry.get("channel")
        if not isinstance(kind,str) or not isinstance(channel,str):
            deny("W_SHIFT_MANUAL_CLASSIFICATION_UNKNOWN",409)
        if channel=="CASH" and kind in {"INCOME_TEST","EXPENSE_TEST","CANCEL_TEST","FORWARD_AMENDMENT_TEST"}:
            manual_cash_draft+=value
        else:
            manual_unclassified.append({"kind":kind,"channel":channel,"signedAmountXaf":value})
        if abs(manual_cash_draft)>MAX_XAF:deny("W_SHIFT_MANUAL_DRAFT_SUM_OVERFLOW")

    ar=raw.get("receivableEvents")
    if not isinstance(ar,dict):deny("W_SHIFT_AR_SOURCE_MISSING",409)
    ar_source=safe_money(ar.get("sourceGrossXaf"),"AR_SOURCE_MARKER")
    if type(ar.get("count")) is not int or ar["count"]<0:
        deny("W_SHIFT_INVALID_AR_MARKER_COUNT",409)

    opening=body.opening_cash_xaf
    expected=opening+cash
    if expected>MAX_XAF:deny("W_SHIFT_EXPECTED_CASH_OVERFLOW")
    counted=body.physically_counted_cash_xaf
    validate_note_counts(body.piece_counts,counted)
    variance=counted-expected
    return {
      "grade":"SYNTHETIC_TEST_ONLY_NOT_OFFICIAL_RECONCILIATION",
      "businessDay":body.business_day.isoformat(),"shift":body.shift,
      "windowStartUtc":raw["start"],"windowEndExclusiveUtc":raw["endExclusive"],
      "tenant":TENANT,"branch":BRANCH,
      "openingCashXaf":opening,"cashReceivedTenderTestXaf":cash,
      "expectedCashTestXaf":expected,"physicalCashCountXaf":counted,
      "varianceSignedXaf":variance,
      "varianceClassification":"SURPLUS" if variance>0 else (
        "SHORTAGE" if variance<0 else "BALANCED_TEST"),
      "grossPosSalesXaf":gross,"discountsXaf":discount,"netDueXaf":net,
      "providerPendingIntentXaf":provider_pending,
      "otherTenderUnverified":other_tender,
      "manualCashDraftSignedXafNotCounted":manual_cash_draft,
      "manualOtherDraftsNotCounted":manual_unclassified,
      "arOriginalGrossMarkerXafNotCounted":ar_source,
      "cashDenominationCountVerified":body.piece_counts is not None,
      "discrepancyNote":body.discrepancy_note,
      "physicalCountsDoNotCreateFinanceEvents":True,
      "pendingIndependentReview":True,"officialReconciliationClosed":False,
      "financePosted":False,"cashPosted":False,"PSPSettled":False,
      "printerTriggered":False,"genuinePc5":False,"g3Admitted":False,
      "warning":"Sales, offers, discounts, provider intentions, A/R markers and Finance drafts are NOT extra cash; do not add them twice. Variance is never auto-cleared."
    }

@handoff_router.post("/shift-handoff/preview")
def shift_handoff_preview(body:ShiftHandoffPreview,actor=Depends(auth)):
    actor_role(actor,{"MERCHANT_TEST","REVIEWER_TEST","CLOSER_TEST"})
    # Uses existing DB-backed read API; cashier access requires independently
    # scoped R4 permission route, not an unsafe role bypass.
    snapshot=daily(day=body.business_day,shift=body.shift,actor=actor)
    return from_native_daily(body,snapshot)
