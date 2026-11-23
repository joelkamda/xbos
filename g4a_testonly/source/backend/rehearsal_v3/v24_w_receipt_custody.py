"""W V24 R6 detachable synthetic TEST receipt / reprint custody.

The only effects permitted here are durable TEST request/review/audit rows,
created in a separately approved isolated PG17 database with additive DDL.
No printer/driver/network, PC5 credential, settlement, or live WND effects.
Source snapshot is tied to one tenant+branch order and revalidated under the
order lock for each state transition and the eventual TEST-only preview.
"""
from __future__ import annotations
import hashlib
import json
import uuid
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from psycopg import errors
from .api import auth,TENANT,BRANCH
from .seed import connect
from .v24_native_api import actor_role
from v24_pos_preview import Line,Tender,preview as receipt_preview

reprint_router=APIRouter(
    prefix="/api/v3/v24/w/receipt-custody",
    tags=["isolated-w-receipt-request-review-preview"]
)

class ReprintRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")
    idem:str=Field(min_length=8,max_length=100,pattern=r"^[a-zA-Z0-9._:-]+$")
    reason:str=Field(min_length=8,max_length=400)

class ReprintReview(BaseModel):
    model_config=ConfigDict(extra="forbid")
    revision:int=Field(ge=1)
    decision:Literal["APPROVE_PREVIEW_TEST","REJECT_TEST"]
    reason:str=Field(min_length=8,max_length=400)

def deny(code:str,status:int=409):
    raise HTTPException(status_code=status,detail=code)

def _source_snapshot(c,order_id):
    """No real WND; order lock serializes original TEST discount/tender edits."""
    c.execute("""SELECT id::text,amount_xaf,status,zone
        FROM v3r_orders WHERE id=%s AND tenant_id=%s AND branch_id=%s FOR UPDATE""",
        (order_id,TENANT,BRANCH))
    order=c.fetchone()
    if not order:deny("REPRINT_ORDER_SCOPE_DENIED",404)
    c.execute("""SELECT l.sku,p.name,l.quantity,l.unit_xaf,l.line_xaf
        FROM v3r_order_lines l JOIN v3r_products p ON p.sku=l.sku
        WHERE l.order_id=%s ORDER BY l.sku""",(order_id,))
    lines=c.fetchall()
    if not lines:deny("REPRINT_EMPTY_SOURCE_ORDER")
    c.execute("""SELECT channel,amount_xaf,status,idem FROM v24_tender_intents
        WHERE order_id=%s ORDER BY idem,channel""",(order_id,))
    tender=c.fetchall()
    c.execute("""SELECT amount_xaf FROM v24_order_discounts
        WHERE order_id=%s""",(order_id,))
    disc=c.fetchone()
    discount=int(disc["amount_xaf"]) if disc else 0
    # Canonical primitive types only; sort keys and use stable UTF8.
    payload={
      "tenant_id":TENANT,"branch_id":BRANCH,
      "order_id":str(order_id),
      "order":{"amount_xaf":int(order["amount_xaf"]),"status":order["status"],
               "zone":order["zone"]},
      "lines":[{
        "sku":x["sku"],"name":x["name"],
        "quantity":int(x["quantity"]),"unit_xaf":int(x["unit_xaf"]),
        "line_xaf":int(x["line_xaf"])}
        for x in lines],
      "tenders":[{
        "channel":x["channel"],"amount_xaf":int(x["amount_xaf"]),
        "status":x["status"],"idem":x["idem"]}
        for x in tender],
      "discount_xaf":discount
    }
    if (any(x["line_xaf"]!=x["quantity"]*x["unit_xaf"] for x in payload["lines"])
        or sum(x["line_xaf"] for x in payload["lines"])!=payload["order"]["amount_xaf"]):
        deny("REPRINT_ORDER_LINE_SOURCE_TOTAL_MISMATCH")
    raw=json.dumps(payload,sort_keys=True,separators=(",",":"),
                   ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest(),payload

def _audit(c,ref,action,who,metadata=None):
    c.execute("""INSERT INTO v24_w_receipt_custody_audit(
        request_id,action,actor,details)
        VALUES(%s,%s,%s,%s::jsonb)""",
        (ref,action,who,json.dumps(metadata or {},sort_keys=True)))

def _request_row(c,request_id):
    c.execute("""SELECT id,order_id,source_sha256,revision,
                       status,requested_by,reviewed_by
        FROM v24_w_receipt_custody
        WHERE id=%s AND tenant_id=%s AND branch_id=%s FOR UPDATE""",
        (request_id,TENANT,BRANCH))
    row=c.fetchone()
    if not row:deny("REPRINT_REQUEST_SCOPE_DENIED",404)
    return row

@reprint_router.post("/orders/{order_id}/request")
def request_reprint(order_id:uuid.UUID,body:ReprintRequest,actor=Depends(auth)):
    who=actor_role(actor,{"CASHIER_TEST","MERCHANT_TEST"})
    ref=uuid.uuid4()
    try:
        with connect() as db:
            with db.cursor() as c:
                fingerprint,source=_source_snapshot(c,order_id)
                c.execute("""INSERT INTO v24_w_receipt_custody(
                    id,tenant_id,branch_id,order_id,request_key,reason,
                    source_sha256,status,revision,requested_by)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,
                           'PENDING_REVIEW_TEST',1,%s)""",
                    (ref,TENANT,BRANCH,order_id,body.idem,body.reason,
                     fingerprint,who))
                _audit(c,ref,"REQUEST_TEST",who,{"source_sha256":fingerprint})
            db.commit()
    except errors.UniqueViolation:
        deny("REPRINT_REQUEST_REPLAY_DENIED")
    return {"requestId":str(ref),"sourceFingerprintSha256":fingerprint,
            "status":"PENDING_REVIEW_TEST","revision":1,
            "needsIndependentReview":True,"realPrinterAuthorized":False,
            "genuinePc5":False,"officialReceiptReprinted":False}

@reprint_router.post("/requests/{request_id}/review")
def review_reprint(request_id:uuid.UUID,body:ReprintReview,actor=Depends(auth)):
    who=actor_role(actor,{"REVIEWER_TEST"})
    with connect() as db:
        with db.cursor() as c:
            row=_request_row(c,request_id)
            if row["status"]!="PENDING_REVIEW_TEST" or row["revision"]!=body.revision:
                deny("REPRINT_STALE_OR_ALREADY_REVIEWED")
            if row["requested_by"]==who:
                deny("REPRINT_SELF_REVIEW_DENIED",403)
            current,_=_source_snapshot(c,row["order_id"])
            if current!=row["source_sha256"]:
                deny("REPRINT_SOURCE_CHANGED_SINCE_REQUEST")
            approved=body.decision=="APPROVE_PREVIEW_TEST"
            state="PREVIEW_APPROVED_TEST" if approved else "REJECTED_TEST"
            c.execute("""UPDATE v24_w_receipt_custody SET
                status=%s,revision=revision+1,reviewed_by=%s,
                review_reason=%s,reviewed_at=NOW()
                WHERE id=%s AND tenant_id=%s AND branch_id=%s
                  AND revision=%s AND status='PENDING_REVIEW_TEST'
                RETURNING revision""",
                (state,who,body.reason,request_id,TENANT,BRANCH,
                 body.revision))
            updated=c.fetchone()
            if not updated:deny("REPRINT_CONCURRENT_REVIEW_DENIED")
            _audit(c,request_id,body.decision,who,{"source_sha256":current})
        db.commit()
    return {"requestId":str(request_id),"status":state,
            "revision":updated["revision"],"independentReviewerTest":True,
            "noPhysicalPrinterEffect":True,"genuinePc5":False,
            "officialFinancePosting":False}

@reprint_router.get("/requests/{request_id}/preview")
def approved_reprint_preview(request_id:uuid.UUID,actor=Depends(auth)):
    actor_role(actor,{"CASHIER_TEST","MERCHANT_TEST"})
    with connect() as db:
        with db.cursor() as c:
            row=_request_row(c,request_id)
            if row["status"]!="PREVIEW_APPROVED_TEST":
                deny("REPRINT_NOT_APPROVED_FOR_PREVIEW")
            current,source=_source_snapshot(c,row["order_id"])
            if current!=row["source_sha256"]:
                deny("REPRINT_SOURCE_CHANGED_SINCE_REVIEW")
    # Pure preview. Does not write a "printed" marker or call a device.
    try:
        pure=receipt_preview(
          order_id=source["order_id"],
          receipt_no="TEST-"+source["order_id"][:8],
          merchant="WND V24 ISOLATED TEST",tax_id="TEST-ONLY-NO-NIU",
          lines=[Line(x["sku"],x["name"],x["quantity"],x["unit_xaf"])
                 for x in source["lines"]],
          tenders=[Tender(x["channel"],x["amount_xaf"],x["status"],x["idem"])
                   for x in source["tenders"]],
          discount_xaf=source["discount_xaf"],
          source_mode="TEST")
    except (ValueError,PermissionError):
        deny("REPRINT_SOURCE_NO_LONGER_PREVIEWABLE")
    return {
      "requestId":str(request_id),"reviewedSourceSha256":current,
      "state":"APPROVED_DUPLICATE_PREVIEW_TEST_ONLY",
      "receipt":pure,
      "banner":"DUPLICATE TEST PREVIEW ONLY / NOT A FISCAL RECEIPT",
      "printed":False,"printCount":0,
      "realPSP":False,"financePosted":False,"genuinePc5":False
    }
