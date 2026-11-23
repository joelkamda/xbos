"""PCR V24 bounded TEST integration on native V3 PostgreSQL/domain tables.
No external/payment/printer calls; synthetic roles are NOT PC5 credentials.
"""
from __future__ import annotations
import csv,io,uuid,os
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
from fastapi import APIRouter,Depends,HTTPException,Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel,Field
from psycopg import errors
from .api import auth,TENANT,BRANCH
from .v24_pk_native_r7 import guard_synthetic_product_publish
from .v24_pa_test_publish_grant import require_native_test_publish_grant
from .seed import connect
from v24_reports import page as report_page,ReportCursorError
from v24_pos_preview import Line,Tender,preview as receipt_preview

r=APIRouter(prefix="/api/v3/v24",tags=["isolated-v24-native-integration"])
ROLE={"merchant":"MERCHANT_TEST","reviewer":"REVIEWER_TEST","cashier":"CASHIER_TEST","closer":"CLOSER_TEST"}
ZONE=("MAIN","VIP","BAR")
def stop(status,code):raise HTTPException(status_code=status,detail=code)
def actor_role(actor, allowed):
    with connect() as db:
        with db.cursor() as c:
            c.execute("SELECT role FROM v3r_operator WHERE username=%s",(actor["username"],))
            x=c.fetchone()
    if not x or x["role"] not in allowed:stop(403,"TEST_NATIVE_ROLE_DENIED")
    return actor["username"]
def set_product(c,sku,action,who):
    """Audit exactly one revision of the same tenant/branch's TEST source row."""
    c.execute("SELECT * FROM v24_product_workflow WHERE sku=%s AND tenant_id=%s AND branch_id=%s",
              (sku,TENANT,BRANCH))
    p=c.fetchone()
    if not p:stop(404,"PRODUCT_SCOPE_DENIED")
    c.execute("INSERT INTO v24_product_audit(sku,revision,action,actor,state) VALUES(%s,%s,%s,%s,%s)",
              (sku,p["revision"],action,who,__import__("json").dumps(p,default=str)))
    return p
def get_product(c,sku,*,lock=False):
    """SELECT FOR UPDATE serializes all edits, reviews, publish and deactivation."""
    query="SELECT * FROM v24_product_workflow WHERE sku=%s AND tenant_id=%s AND branch_id=%s"
    if lock:query+=" FOR UPDATE"
    c.execute(query,(sku,TENANT,BRANCH))
    p=c.fetchone()
    if not p:stop(404,"PRODUCT_SCOPE_DENIED")
    return p

def update_product_cas(c,sql,params,code="STALE_PRODUCT_REVISION"):
    """Fail closed if an expected-state/revision mutation affected no row."""
    c.execute(sql,params)
    if c.rowcount!=1:stop(409,code)
class Draft(BaseModel):
    name:str=Field(min_length=2,max_length=90)
class Edit(BaseModel):
    revision:int=Field(ge=1)
    name:str=Field(min_length=2,max_length=90)
    category:str=Field(min_length=2,max_length=50)
    family:str
    unit:str=Field(min_length=1,max_length=40)
    main_xaf:int=Field(ge=0)
    vip_xaf:int=Field(ge=0)
    bar_xaf:int=Field(ge=0)
    stock_qty:int|None=Field(default=None,ge=0)
class Revision(BaseModel):
    revision:int=Field(ge=1)
    price_revisions:tuple[int,int,int]|None=None
@r.post("/products/draft")
def product_draft(body:Draft,actor=Depends(auth)):
    who=actor_role(actor,{"MERCHANT_TEST"})
    sku="V24-TEST-"+uuid.uuid4().hex[:12].upper()
    with connect() as db:
        with db.cursor() as c:
            c.execute("INSERT INTO v24_product_workflow(sku,tenant_id,branch_id,name,creator) VALUES(%s,%s,%s,%s,%s)",
                      (sku,TENANT,BRANCH,body.name.strip(),who))
            p=set_product(c,sku,"DRAFT",who)
        db.commit()
    return {"sku":sku,"revision":p["revision"],"state":p["status"],"genuinePc5":False}
@r.put("/products/{sku}")
def product_edit(sku:str,body:Edit,actor=Depends(auth)):
    who=actor_role(actor,{"MERCHANT_TEST"})
    if body.family not in {"bar","kitchen","other"}:stop(422,"FAMILY_INVALID")
    with connect() as db:
        with db.cursor() as c:
            p=get_product(c,sku,lock=True)
            if p["creator"]!=who:stop(403,"PRODUCT_CREATOR_DENIED")
            if p["revision"]!=body.revision:stop(409,"STALE_PRODUCT_REVISION")
            if p["status"] not in {"DRAFT_TEST","REVIEW_TEST"}:stop(409,"PRODUCT_LOCKED")
            update_product_cas(c,"""UPDATE v24_product_workflow SET name=%s,category=%s,family=%s,unit=%s,
                         main_xaf=%s,vip_xaf=%s,bar_xaf=%s,stock_qty=%s,
                         status='DRAFT_TEST',reviewer=NULL,revision=revision+1
                         WHERE sku=%s AND tenant_id=%s AND branch_id=%s
                           AND revision=%s AND status IN ('DRAFT_TEST','REVIEW_TEST')""",
                         (body.name.strip(),body.category.upper(),body.family,body.unit,
                          body.main_xaf,body.vip_xaf,body.bar_xaf,body.stock_qty,
                          sku,TENANT,BRANCH,body.revision))
            p=set_product(c,sku,"REVISE",who)
        db.commit()
    return {"sku":sku,"revision":p["revision"],"state":p["status"],
            "priceRevisions":[p[z.lower()+"_price_revision"] for z in ZONE]}
@r.post("/products/{sku}/review")
def product_review(sku:str,body:Revision,actor=Depends(auth)):
    who=actor_role(actor,{"MERCHANT_TEST"})
    with connect() as db:
        with db.cursor() as c:
            p=get_product(c,sku,lock=True)
            if p["creator"]!=who:stop(403,"CREATOR_DENIED")
            if p["revision"]!=body.revision:stop(409,"STALE_PRODUCT_REVISION")
            if p["status"]!="DRAFT_TEST" or any(p[x] is None for x in
                    ("category","family","unit","main_xaf","vip_xaf","bar_xaf")):
                stop(409,"PRODUCT_INCOMPLETE_OR_NOT_DRAFT")
            update_product_cas(c,"""UPDATE v24_product_workflow SET status='REVIEW_TEST',revision=revision+1
                         WHERE sku=%s AND tenant_id=%s AND branch_id=%s
                           AND revision=%s AND status='DRAFT_TEST'""",
                         (sku,TENANT,BRANCH,body.revision))
            p=set_product(c,sku,"REQUEST_REVIEW",who)
        db.commit()
    return {"sku":sku,"revision":p["revision"],"state":p["status"],
            "priceRevisions":[p[z.lower()+"_price_revision"] for z in ZONE]}
@r.post("/products/{sku}/publish")
def product_publish(sku:str,body:Revision,actor=Depends(auth)):
    who=actor_role(actor,{"REVIEWER_TEST"})
    with connect() as db:
        with db.cursor() as c:
            p=get_product(c,sku,lock=True)
            if p["revision"]!=body.revision:stop(409,"STALE_PRODUCT_REVISION")
            if p["status"]!="REVIEW_TEST" or p["creator"]==who:stop(409,"SEPARATE_REVIEW_REQUIRED")
            pa_scope=require_native_test_publish_grant(c,actor,TENANT,BRANCH)
            pk_scope=guard_synthetic_product_publish(c,p,body.price_revisions,who,TENANT,BRANCH)
            c.execute("""INSERT INTO v3r_products(sku,name,category,family,unit,stock_qty)
                         VALUES(%s,%s,%s,%s,%s,%s)""",
                      (sku,p["name"],p["category"],p["family"],p["unit"],p["stock_qty"]))
            for z in ZONE:
                c.execute("INSERT INTO v3r_prices(sku,zone,amount_xaf) VALUES(%s,%s,%s)",
                          (sku,z,p[z.lower()+"_xaf"]))
            update_product_cas(c,"""UPDATE v24_product_workflow SET status='PUBLISHED_TEST',
                         reviewer=%s,revision=revision+1
                         WHERE sku=%s AND tenant_id=%s AND branch_id=%s
                           AND revision=%s AND status='REVIEW_TEST'""",
                         (who,sku,TENANT,BRANCH,body.revision))
            p=set_product(c,sku,"PUBLISH",who)
        db.commit()
    return {"sku":sku,"revision":p["revision"],"state":p["status"],
            "nativeCatalog":True,"r7NativePkPreflight":pk_scope,**pa_scope,
            "genuinePc5":False,"realPackCertification":False}
@r.post("/products/{sku}/deactivate")
def product_deactivate(sku:str,body:Revision,actor=Depends(auth)):
    who=actor_role(actor,{"REVIEWER_TEST"})
    with connect() as db:
        with db.cursor() as c:
            p=get_product(c,sku,lock=True)
            if p["revision"]!=body.revision or p["status"]!="PUBLISHED_TEST":
                stop(409,"PRODUCT_STATE_OR_REVISION_DENIED")
            update_product_cas(c,"""UPDATE v3r_products
                         SET active=FALSE,source_revision=source_revision+1
                         WHERE sku=%s AND active=TRUE""",(sku,),
                         "PRODUCT_NATIVE_ALREADY_INACTIVE")
            update_product_cas(c,"""UPDATE v24_product_workflow
                         SET status='INACTIVE_TEST',revision=revision+1
                         WHERE sku=%s AND tenant_id=%s AND branch_id=%s
                           AND revision=%s AND status='PUBLISHED_TEST'""",
                         (sku,TENANT,BRANCH,body.revision),"PRODUCT_STATE_OR_REVISION_DENIED")
            p=set_product(c,sku,"DEACTIVATE",who)
        db.commit()
    return {"sku":sku,"state":p["status"],"nativeCatalogActive":False}
@r.get("/products/{sku}/history")
def product_history(sku:str,actor=Depends(auth)):
    actor_role(actor,{"MERCHANT_TEST","REVIEWER_TEST","CASHIER_TEST"})
    with connect() as db:
        with db.cursor() as c:
            get_product(c,sku)
            c.execute("SELECT revision,action,actor,at FROM v24_product_audit WHERE sku=%s ORDER BY revision",(sku,))
            rows=c.fetchall()
    return {"sku":sku,"history":rows,"genuinePc5":False}

class CountDraft(BaseModel):
    sku:str
class CountSave(BaseModel):
    revision:int=Field(ge=1)
    count_qty:int=Field(ge=0)
@r.post("/stock/counts")
def new_count(body:CountDraft,actor=Depends(auth)):
    who=actor_role(actor,{"MERCHANT_TEST"})
    ident=uuid.uuid4()
    with connect() as db:
        with db.cursor() as c:
            c.execute("SELECT sku FROM v3r_products WHERE sku=%s AND active",(body.sku,))
            if not c.fetchone():stop(404,"SKU_NOT_FOUND")
            c.execute("INSERT INTO v24_stock_counts(id,tenant_id,sku,author) VALUES(%s,%s,%s,%s)",
                      (ident,TENANT,body.sku,who))
            c.execute("INSERT INTO v24_stock_audit(draft_id,action,actor,details) VALUES(%s,'CREATE',%s,'{}')",(ident,who))
        db.commit()
    return {"draftId":str(ident),"revision":1,"state":"DRAFT_TEST"}
@r.put("/stock/counts/{draft_id}")
def save_count(draft_id:uuid.UUID,body:CountSave,actor=Depends(auth)):
    who=actor_role(actor,{"MERCHANT_TEST"})
    with connect() as db:
        with db.cursor() as c:
            c.execute("UPDATE v24_stock_counts SET count_qty=%s,revision=revision+1 WHERE id=%s AND tenant_id=%s AND revision=%s AND status='DRAFT_TEST' AND author=%s RETURNING revision",
                      (body.count_qty,draft_id,TENANT,body.revision,who))
            row=c.fetchone()
            if not row:stop(409,"STALE_OR_UNAUTHORIZED_STOCK_DRAFT")
            c.execute("INSERT INTO v24_stock_audit(draft_id,action,actor,details) VALUES(%s,'SAVE',%s,%s)",
                      (draft_id,who,__import__("json").dumps({"count":body.count_qty})))
        db.commit()
    return {"draftId":str(draft_id),"revision":row["revision"],"saved":True}
@r.get("/stock/counts/{draft_id}")
def count_detail(draft_id:uuid.UUID,actor=Depends(auth)):
    actor_role(actor,{"MERCHANT_TEST","REVIEWER_TEST"})
    with connect() as db:
        with db.cursor() as c:
            c.execute("SELECT * FROM v24_stock_counts WHERE id=%s AND tenant_id=%s",(draft_id,TENANT))
            row=c.fetchone()
    if not row:stop(404,"COUNT_NOT_FOUND")
    return {"draft":row}
@r.post("/stock/counts/{draft_id}/approve")
def approve_count(draft_id:uuid.UUID,body:Revision,actor=Depends(auth)):
    who=actor_role(actor,{"REVIEWER_TEST"})
    with connect() as db:
        with db.cursor() as c:
            c.execute("SELECT * FROM v24_stock_counts WHERE id=%s AND tenant_id=%s FOR UPDATE",(draft_id,TENANT))
            draft=c.fetchone()
            if not draft or draft["revision"]!=body.revision or draft["status"]!="DRAFT_TEST" or draft["count_qty"] is None:
                stop(409,"STOCK_COUNT_STATE_DENIED")
            if draft["author"]==who:stop(403,"INDEPENDENT_REVIEW_REQUIRED")
            c.execute("SELECT stock_qty,family FROM v3r_products WHERE sku=%s FOR UPDATE",(draft["sku"],))
            prod=c.fetchone()
            if prod["stock_qty"] is None:stop(409,"STOCK_WITHHELD_REQUIRES_SOURCE_POLICY")
            delta=draft["count_qty"]-prod["stock_qty"]
            if delta:
                c.execute("UPDATE v3r_products SET stock_qty=%s WHERE sku=%s",(draft["count_qty"],draft["sku"]))
                c.execute("INSERT INTO v3r_stock_movements(id,sku,delta,quantity_after) VALUES(%s,%s,%s,%s)",
                          (uuid.uuid4(),draft["sku"],delta,draft["count_qty"]))
            c.execute("UPDATE v24_stock_counts SET status='APPROVED_TEST',revision=revision+1,reviewer=%s WHERE id=%s",(who,draft_id))
            c.execute("INSERT INTO v24_stock_audit(draft_id,action,actor,details) VALUES(%s,'APPROVE',%s,%s)",
                      (draft_id,who,__import__("json").dumps({"delta":delta})))
        db.commit()
    return {"draftId":str(draft_id),"delta":delta,"actualQty":draft["count_qty"],
            "nativeMovement":bool(delta),"realFinancePosted":False}
@r.get("/stock/{sku}/movements")
def movements(sku:str,as_of:datetime|None=None,actor=Depends(auth)):
    actor_role(actor,{"MERCHANT_TEST","REVIEWER_TEST","CASHIER_TEST"})
    with connect() as db:
        with db.cursor() as c:
            c.execute("SELECT stock_qty,family FROM v3r_products WHERE sku=%s",(sku,))
            p=c.fetchone()
            if not p:stop(404,"SKU_NOT_FOUND")
            c.execute("SELECT id::text,delta,quantity_after,created_at FROM v3r_stock_movements WHERE sku=%s AND (%s::timestamptz IS NULL OR created_at<=%s) ORDER BY created_at,id",
                      (sku,as_of,as_of))
            rows=c.fetchall()
    return {"sku":sku,"currentQty":p["stock_qty"],"movements":rows,
            "cogsPolicy":"FOOD_MANUAL_TEST" if p["family"]=="kitchen" else "DRINK_AUTO_TEST",
            "historicalAsOfBalanceProven":False}

class TenderBody(BaseModel):
    idem:str=Field(min_length=8,max_length=100)
    channel:str
    amount_xaf:int=Field(gt=0)
    state:str
@r.post("/orders/{order_id}/tender")
def tender(order_id:uuid.UUID,body:TenderBody,actor=Depends(auth)):
    who=actor_role(actor,{"CASHIER_TEST"})
    if body.channel not in {"CASH","MTN","ORANGE","BANK","XAFPAY_TEST"}:stop(422,"CHANNEL_INVALID")
    if (body.channel=="CASH" and body.state!="CASH_RECEIVED_TEST") or (
        body.channel!="CASH" and body.state!="PROVIDER_PENDING_TEST"):
        stop(422,"PROVIDER_NOT_SETTLED_TEST")
    with connect() as db:
        with db.cursor() as c:
            c.execute("SELECT amount_xaf,status FROM v3r_orders WHERE id=%s AND tenant_id=%s FOR UPDATE",
                      (order_id,TENANT))
            o=c.fetchone()
            if not o:stop(404,"ORDER_NOT_FOUND")
            if o["status"]!="UNPAID_TEST":stop(409,"NATIVE_ORDER_ALREADY_SETTLED")
            # R6 SOF cross-owner invariant: once A/R is linked, original tender
            # allocation is immutable. New installments use SOF A/R route only.
            c.execute("""SELECT 1 FROM v24_ar_obligations
                         WHERE order_id=%s AND tenant_id=%s AND branch_id=%s""",
                      (order_id,TENANT,BRANCH))
            if c.fetchone():stop(409,"SOF_AR_LINKED_SOURCE_TENDERS_FROZEN")
            c.execute("SELECT 1 FROM v24_tender_intents WHERE order_id=%s AND idem=%s",(order_id,body.idem))
            if c.fetchone():stop(409,"TEST_TENDER_REPLAY_DENIED")
            c.execute("SELECT COALESCE(SUM(amount_xaf),0) AS n FROM v24_tender_intents WHERE order_id=%s",(order_id,))
            existing=int(c.fetchone()["n"])
            c.execute("SELECT amount_xaf FROM v24_order_discounts WHERE order_id=%s",(order_id,))
            d=c.fetchone()
            net_due=o["amount_xaf"]-(int(d["amount_xaf"]) if d else 0)
            if existing+body.amount_xaf>net_due:stop(409,"TEST_TENDER_OVERALLOCATION")
            c.execute("INSERT INTO v24_tender_intents(id,order_id,tenant_id,branch_id,idem,channel,amount_xaf,status,created_by) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                      (uuid.uuid4(),order_id,TENANT,BRANCH,body.idem,body.channel,body.amount_xaf,body.state,who))
        db.commit()
    return {"saved":True,"paid":False,"providerCalled":False,"financePosted":False}
@r.get("/orders/{order_id}/allocation")
def allocation(order_id:uuid.UUID,actor=Depends(auth)):
    actor_role(actor,{"CASHIER_TEST","MERCHANT_TEST","REVIEWER_TEST"})
    with connect() as db:
        with db.cursor() as c:
            c.execute("SELECT id::text,amount_xaf,status,zone FROM v3r_orders WHERE id=%s AND tenant_id=%s",(order_id,TENANT))
            o=c.fetchone()
            if not o:stop(404,"ORDER_NOT_FOUND")
            c.execute("SELECT channel,amount_xaf,status FROM v24_tender_intents WHERE order_id=%s ORDER BY created_at,id",(order_id,))
            rows=c.fetchall()
            c.execute("SELECT amount_xaf FROM v24_order_discounts WHERE order_id=%s",(order_id,))
            d=c.fetchone()
    discount=int(d["amount_xaf"]) if d else 0
    cash=sum(int(x["amount_xaf"]) for x in rows if x["status"]=="CASH_RECEIVED_TEST")
    pending=sum(int(x["amount_xaf"]) for x in rows if x["status"]=="PROVIDER_PENDING_TEST")
    return {"orderId":str(order_id),"orderTotalXaf":o["amount_xaf"],"tenders":rows,
            "discountXaf":discount,"netDueXaf":o["amount_xaf"]-discount,
            "cashReceivedTestXaf":cash,"providerPendingTestXaf":pending,
            "outstandingXaf":o["amount_xaf"]-discount-cash,"paid":False,"realPSP":False}
@r.get("/orders/{order_id}/receipt-preview")
def receipt(order_id:uuid.UUID,actor=Depends(auth)):
    actor_role(actor,{"CASHIER_TEST","MERCHANT_TEST"})
    with connect() as db:
        with db.cursor() as c:
            c.execute("SELECT id::text,amount_xaf FROM v3r_orders WHERE id=%s AND tenant_id=%s",(order_id,TENANT))
            o=c.fetchone()
            if not o:stop(404,"ORDER_NOT_FOUND")
            c.execute("SELECT l.sku,p.name,l.quantity,l.unit_xaf FROM v3r_order_lines l JOIN v3r_products p ON p.sku=l.sku WHERE order_id=%s",(order_id,))
            lines=c.fetchall()
            c.execute("SELECT channel,amount_xaf,status,idem FROM v24_tender_intents WHERE order_id=%s",(order_id,))
            ts=c.fetchall()
            c.execute("SELECT amount_xaf FROM v24_order_discounts WHERE order_id=%s",(order_id,))
            d=c.fetchone()
    discount=int(d["amount_xaf"]) if d else 0
    items=[Line(x["sku"],x["name"],x["quantity"],x["unit_xaf"]) for x in lines]
    tenders=[Tender(x["channel"],x["amount_xaf"],x["status"],x["idem"]) for x in ts]
    return receipt_preview(order_id=str(order_id),receipt_no="TEST-"+str(order_id)[:8],
           merchant="WND V24 ISOLATED TEST",tax_id="TEST-ONLY-NO-NIU",
           lines=items,tenders=tenders,discount_xaf=discount)

@r.get("/reports/page")
def report(as_of:datetime,limit:int=Query(100,ge=1,le=500),cursor:str|None=None,
           channel:str|None=None,kind:str|None=None,tenant_id:int=TENANT,actor=Depends(auth)):
    actor_role(actor,{"REVIEWER_TEST","CLOSER_TEST","MERCHANT_TEST"})
    if tenant_id!=TENANT:stop(403,"TENANT_DENIED")
    try:
        return report_page(connect,tenant=TENANT,branch=BRANCH,as_of=as_of,
             secret=bytes.fromhex(os.environ["V24_CURSOR_SECRET_HEX"]),
             limit=limit,cursor=cursor,channel=channel,kind=kind)
    except ReportCursorError as ex:stop(422,str(ex))
@r.get("/reports/export-test")
def report_export(as_of:datetime,tenant_id:int=TENANT,kind:str|None=None,channel:str|None=None,actor=Depends(auth)):
    actor_role(actor,{"REVIEWER_TEST","CLOSER_TEST"})
    if tenant_id!=TENANT:stop(403,"TENANT_DENIED")
    cursor=None;total=0;out=io.StringIO();writer=csv.writer(out)
    writer.writerow(["REF","KIND","CHANNEL","SIGNED_XAF","EFFECTIVE_AT","STATUS"])
    while True:
        try:
            x=report_page(connect,tenant=TENANT,branch=BRANCH,as_of=as_of,
                 secret=bytes.fromhex(os.environ["V24_CURSOR_SECRET_HEX"]),
                 limit=500,cursor=cursor,kind=kind,channel=channel)
        except ReportCursorError as ex:stop(422,str(ex))
        for row in x["rows"]:
            def safe(t):
                val=str(t)
                return "'"+val if val.lstrip().startswith(("=","+","-","@")) else val
            writer.writerow([safe(row[z]) for z in
                ("ref","kind","channel","signed_amount_xaf","effective_at","status")])
        total+=len(x["rows"])
        cursor=x["nextCursor"]
        if not cursor:break
        if total>100000:stop(422,"TEST_EXPORT_SIZE_BOUND_EXCEEDED")
    return PlainTextResponse(out.getvalue(),media_type="text/csv",
           headers={"X-TEST-ROW-COUNT":str(total),"X-Data-Grade":"SYNTHETIC_TEST_ONLY"})

from datetime import timedelta
def business_day_local(v:datetime):
    if v.tzinfo is None or v.utcoffset() is None:stop(422,"NAIVE_BUSINESS_TIMESTAMP")
    local=v.astimezone(ZoneInfo("Africa/Douala"))
    return (local-timedelta(days=1)).date() if local.hour<8 else local.date()
def business_period(v:datetime):
    return business_day_local(v).strftime("%Y-%m")
def business_shift(v:datetime):
    local=v.astimezone(ZoneInfo("Africa/Douala"))
    return "DAY" if 8<=local.hour<18 else "NIGHT"
@r.get("/business-time")
def test_business_time(at:datetime,actor=Depends(auth)):
    actor_role(actor,{"MERCHANT_TEST","REVIEWER_TEST","CASHIER_TEST","CLOSER_TEST"})
    day=business_day_local(at)
    return {"businessDate":day.isoformat(),"period":business_period(at),
            "shift":business_shift(at),"businessDayStarts":"08:00 Africa/Douala",
            "nightShiftEndsNextMorning":True,"officialFinancePosting":False}

class FinanceEntry(BaseModel):
    period:str
    amount_xaf:int
    channel:str
    kind:str
    idem:str=Field(min_length=8)
    note:str=Field(min_length=4)
    effective_at:datetime
class CloseBody(BaseModel):
    revision:int=Field(ge=1)
class PeriodOpen(BaseModel):
    period:str
    opening_cash_xaf:int=0
def finance_event(c,period,action,who,ref):
    c.execute("INSERT INTO v24_finance_audit(tenant_id,period,action,actor,reference) VALUES(%s,%s,%s,%s,%s)",
              (TENANT,period,action,who,ref))
def period_get(c,period):
    c.execute("SELECT * FROM v24_finance_periods WHERE tenant_id=%s AND period=%s FOR UPDATE",(TENANT,period))
    p=c.fetchone()
    if not p:stop(404,"PERIOD_NOT_FOUND")
    return p
@r.post("/finance/periods")
def open_period(body:PeriodOpen,actor=Depends(auth)):
    who=actor_role(actor,{"MERCHANT_TEST"})
    with connect() as db:
        with db.cursor() as c:
            c.execute("INSERT INTO v24_finance_periods(tenant_id,period,opening_cash_xaf,prepared_by) VALUES(%s,%s,%s,%s)",
                      (TENANT,body.period,body.opening_cash_xaf,who))
            finance_event(c,body.period,"OPEN_TEST",who,body.period)
        db.commit()
    return {"state":"OPEN_TEST","revision":1,"realPosting":False}
@r.post("/finance/entry")
def finance_entry(body:FinanceEntry,actor=Depends(auth)):
    who=actor_role(actor,{"MERCHANT_TEST"})
    if body.channel not in {"CASH","MTN","ORANGE","BANK"} or (
       body.kind not in {"INCOME_TEST","EXPENSE_TEST"}) or (
       body.amount_xaf==0) or body.effective_at.tzinfo is None:
        stop(422,"FINANCE_TEST_VALIDATION")
    if (body.amount_xaf>0)!=(body.kind=="INCOME_TEST"):
        stop(422,"TEST_FINANCE_SIGN_INVALID")
    if business_period(body.effective_at)!=body.period:
        stop(422,"FINANCE_BUSINESS_PERIOD_MISMATCH")
    ref=uuid.uuid4()
    try:
        with connect() as db:
            with db.cursor() as c:
                p=period_get(c,body.period)
                if p["status"]!="OPEN_TEST":stop(409,"PERIOD_LOCKED")
                c.execute("""INSERT INTO v3r_b_finance_drafts
                  (id,tenant_id,branch_id,idempotency_key,kind,channel,signed_amount_xaf,
                   effective_at,note,created_by)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                   (ref,TENANT,BRANCH,body.idem,body.kind,body.channel,body.amount_xaf,
                    body.effective_at,body.note,who))
                finance_event(c,body.period,"CREATE_TEST",who,str(ref))
            db.commit()
    except errors.UniqueViolation:stop(409,"DUPLICATE_FINANCE_TEST_DENIED")
    return {"ref":str(ref),"state":"DRAFT_TEST","financePosted":False}
class CancelBody(BaseModel):
    period:str
    reason:str=Field(min_length=4)
@r.post("/finance/{entry_id}/cancel")
def cancel_entry(entry_id:uuid.UUID,body:CancelBody,actor=Depends(auth)):
    who=actor_role(actor,{"REVIEWER_TEST"})
    with connect() as db:
        with db.cursor() as c:
            p=period_get(c,body.period)
            if p["status"]!="OPEN_TEST":stop(409,"PERIOD_LOCKED")
            c.execute("SELECT * FROM v3r_b_finance_drafts WHERE id=%s AND tenant_id=%s FOR UPDATE",(entry_id,TENANT))
            source=c.fetchone()
            if not source or source["kind"]=="CANCEL_TEST":stop(409,"CANCEL_ORIGINAL_DENIED")
            c.execute("SELECT 1 FROM v3r_b_finance_drafts WHERE kind='CANCEL_TEST' AND transfer_ref=%s",(str(entry_id),))
            if c.fetchone():stop(409,"ALREADY_CANCELLED_TEST")
            new=uuid.uuid4()
            c.execute("""INSERT INTO v3r_b_finance_drafts
                        (id,tenant_id,branch_id,idempotency_key,kind,channel,
                         signed_amount_xaf,transfer_ref,effective_at,note,created_by)
                         VALUES(%s,%s,%s,%s,'CANCEL_TEST',%s,%s,%s,%s,%s,%s)""",
                      (new,TENANT,BRANCH,"cancel:"+str(entry_id),source["channel"],
                       -int(source["signed_amount_xaf"]),str(entry_id),
                       datetime.now(timezone.utc),body.reason,who))
            finance_event(c,body.period,"COMPENSATING_CANCEL_TEST",who,str(new))
        db.commit()
    return {"cancellationRef":str(new),"originalPreserved":True,"realPosting":False}
@r.post("/finance/periods/{period}/prepare")
def prepare_period(period:str,actor=Depends(auth)):
    who=actor_role(actor,{"MERCHANT_TEST"})
    with connect() as db:
        with db.cursor() as c:
            p=period_get(c,period)
            if p["status"]!="OPEN_TEST":stop(409,"PERIOD_NOT_OPEN")
            c.execute("UPDATE v24_finance_periods SET status='PREPARED_TEST',revision=revision+1,prepared_by=%s WHERE tenant_id=%s AND period=%s",
                      (who,TENANT,period))
            finance_event(c,period,"PREPARE_TEST",who,period)
        db.commit()
    return {"revision":p["revision"]+1,"state":"PREPARED_TEST"}
@r.post("/finance/periods/{period}/review")
def review_period(period:str,body:CloseBody,actor=Depends(auth)):
    who=actor_role(actor,{"REVIEWER_TEST"})
    with connect() as db:
        with db.cursor() as c:
            p=period_get(c,period)
            if p["status"]!="PREPARED_TEST" or body.revision!=p["revision"]:stop(409,"REVIEW_REVISION_DENIED")
            if who==p["prepared_by"]:stop(403,"SELF_REVIEW_DENIED")
            c.execute("UPDATE v24_finance_periods SET status='REVIEWED_TEST',revision=revision+1,reviewed_by=%s WHERE tenant_id=%s AND period=%s",
                      (who,TENANT,period))
            finance_event(c,period,"REVIEW_TEST",who,period)
        db.commit()
    return {"revision":p["revision"]+1,"state":"REVIEWED_TEST"}
@r.post("/finance/periods/{period}/close")
def close_period(period:str,body:CloseBody,actor=Depends(auth)):
    who=actor_role(actor,{"CLOSER_TEST"})
    with connect() as db:
        with db.cursor() as c:
            p=period_get(c,period)
            if p["status"]!="REVIEWED_TEST" or p["revision"]!=body.revision:
                stop(409,"CLOSE_REVISION_DENIED")
            if who in {p["prepared_by"],p["reviewed_by"]}:stop(403,"SEPARATE_CLOSER_REQUIRED")
            start=datetime.strptime(period+"-01","%Y-%m-%d").replace(
                    tzinfo=ZoneInfo("Africa/Douala"),hour=8)
            nxt=(start.replace(day=28)+timedelta(days=4)).replace(day=1,hour=8)
            next_period=nxt.strftime("%Y-%m")
            c.execute("SELECT 1 FROM v24_finance_periods WHERE tenant_id=%s AND period=%s",(TENANT,next_period))
            if c.fetchone():stop(409,"NEXT_PERIOD_ALREADY_OPEN")
            c.execute("""SELECT COALESCE(SUM(signed_amount_xaf),0) AS n FROM v3r_b_finance_drafts
                         WHERE tenant_id=%s AND branch_id=%s
                           AND effective_at >= %s AND effective_at < %s""",
                      (TENANT,BRANCH,start,nxt))
            balance=int(p["opening_cash_xaf"])+int(c.fetchone()["n"])
            c.execute("INSERT INTO v24_finance_periods(tenant_id,period,opening_cash_xaf) VALUES(%s,%s,%s)",
                      (TENANT,next_period,balance))
            c.execute("UPDATE v24_finance_periods SET status='CLOSED_TEST',revision=revision+1,closed_by=%s WHERE tenant_id=%s AND period=%s",
                      (who,TENANT,period))
            finance_event(c,period,"CLOSE_TEST",who,next_period)
        db.commit()
    return {"state":"CLOSED_TEST","nextPeriod":next_period,"carryXaf":balance,
            "realFinancePosted":False,"genuinePC5":False}
@r.get("/finance/periods/{period}")
def get_period(period:str,actor=Depends(auth)):
    actor_role(actor,{"MERCHANT_TEST","REVIEWER_TEST","CLOSER_TEST"})
    with connect() as db:
        with db.cursor() as c:
            p=period_get(c,period)
            c.execute("SELECT seq,action,actor,reference FROM v24_finance_audit WHERE tenant_id=%s AND period=%s ORDER BY seq",
                      (TENANT,period))
            history=c.fetchall()
    return {"period":p,"audit":history,"actualLedger":False}

# V24 native extension R2: discount, resume, COGS and forward-only amendment.
class DiscountBody(BaseModel):
    amount_xaf:int=Field(gt=0)
    reason:str=Field(min_length=4,max_length=160)
@r.post("/orders/{order_id}/discount")
def discount_order(order_id:uuid.UUID,body:DiscountBody,actor=Depends(auth)):
    who=actor_role(actor,{"MERCHANT_TEST"})
    with connect() as db:
        with db.cursor() as c:
            c.execute("SELECT amount_xaf,status FROM v3r_orders WHERE id=%s AND tenant_id=%s FOR UPDATE",(order_id,TENANT))
            order=c.fetchone()
            if not order:stop(404,"ORDER_NOT_FOUND")
            if order["status"]!="UNPAID_TEST" or body.amount_xaf>=order["amount_xaf"]:
                stop(409,"DISCOUNT_STATE_OR_AMOUNT_DENIED")
            c.execute("""SELECT 1 FROM v24_ar_obligations WHERE order_id=%s AND tenant_id=%s AND branch_id=%s""",(order_id,TENANT,BRANCH))
            if c.fetchone():stop(409,"SOF_AR_LINKED_ORDER_DISCOUNT_FROZEN")
            c.execute("SELECT 1 FROM v24_tender_intents WHERE order_id=%s",(order_id,))
            if c.fetchone():stop(409,"DISCOUNT_AFTER_TENDER_DENIED")
            c.execute("SELECT 1 FROM v24_order_discounts WHERE order_id=%s",(order_id,))
            if c.fetchone():stop(409,"DUPLICATE_DISCOUNT_DENIED")
            c.execute("""INSERT INTO v24_order_discounts
                (order_id,tenant_id,branch_id,amount_xaf,reason,created_by)
                VALUES(%s,%s,%s,%s,%s,%s)""",
                (order_id,TENANT,BRANCH,body.amount_xaf,body.reason,who))
        db.commit()
    return {"orderId":str(order_id),"grossSaleXaf":order["amount_xaf"],
            "discountTestExpenseXaf":body.amount_xaf,
            "netDueXaf":order["amount_xaf"]-body.amount_xaf,
            "realFinancePosting":False,"realPayment":False}
@r.get("/orders/pending")
def pending_orders(actor=Depends(auth)):
    actor_role(actor,{"CASHIER_TEST","MERCHANT_TEST"})
    with connect() as db:
        with db.cursor() as c:
            c.execute("""SELECT o.id::text AS order_id,o.amount_xaf,o.zone,o.created_at,
                         COALESCE(d.amount_xaf,0) AS discount_xaf
                         FROM v3r_orders o LEFT JOIN v24_order_discounts d ON d.order_id=o.id
                         WHERE o.tenant_id=%s AND o.branch_id=%s AND o.status='UNPAID_TEST'
                         ORDER BY o.created_at DESC,o.id LIMIT 200""",(TENANT,BRANCH))
            rows=c.fetchall()
    return {"rows":rows,"pendingMeansUnpaidNotProviderPaid":True,"noDuplicateOrderWrite":True}
@r.post("/orders/{order_id}/resume")
def resume_order(order_id:uuid.UUID,actor=Depends(auth)):
    actor_role(actor,{"CASHIER_TEST"})
    with connect() as db:
        with db.cursor() as c:
            c.execute("SELECT id::text,amount_xaf,status,zone FROM v3r_orders WHERE id=%s AND tenant_id=%s",
                      (order_id,TENANT))
            o=c.fetchone()
            if not o:stop(404,"ORDER_NOT_FOUND")
            if o["status"]!="UNPAID_TEST":stop(409,"ORDER_NOT_RESUMABLE")
            c.execute("SELECT sku,quantity,unit_xaf,line_xaf FROM v3r_order_lines WHERE order_id=%s",
                      (order_id,))
            lines=c.fetchall()
    return {"order":o,"lines":lines,"resumed":True,"orderCreated":False,
            "stockMoved":False,"realPayment":False}

class CostConfig(BaseModel):
    policy:str
    unit_cost_xaf:int=Field(ge=0)
@r.post("/stock/{sku}/cost-policy")
def set_stock_cost(sku:str,body:CostConfig,actor=Depends(auth)):
    who=actor_role(actor,{"MERCHANT_TEST"})
    with connect() as db:
        with db.cursor() as c:
            c.execute("SELECT family FROM v3r_products WHERE sku=%s AND active",(sku,))
            p=c.fetchone()
            if not p:stop(404,"SKU_NOT_FOUND")
            expected="DRINK_AUTO_TEST" if p["family"]=="bar" else "FOOD_MANUAL_TEST" if p["family"]=="kitchen" else None
            if body.policy!=expected:stop(422,"FOOD_DRINK_COST_POLICY_DENIED")
            c.execute("""INSERT INTO v24_cost_policies(sku,tenant_id,policy,unit_cost_xaf,created_by)
                         VALUES(%s,%s,%s,%s,%s)
                         ON CONFLICT(sku) DO UPDATE SET policy=EXCLUDED.policy,
                         unit_cost_xaf=EXCLUDED.unit_cost_xaf,
                         revision=v24_cost_policies.revision+1""",
                      (sku,TENANT,body.policy,body.unit_cost_xaf,who))
        db.commit()
    return {"sku":sku,"costRule":body.policy,"nativeStockMovesUsed":True,
            "officialFinancePosted":False}
@r.get("/stock/{sku}/cogs")
def read_cogs(sku:str,actor=Depends(auth)):
    actor_role(actor,{"MERCHANT_TEST","REVIEWER_TEST"})
    with connect() as db:
        with db.cursor() as c:
            c.execute("""SELECT p.family,c.policy,c.unit_cost_xaf
                         FROM v3r_products p LEFT JOIN v24_cost_policies c ON c.sku=p.sku
                         WHERE p.sku=%s""",(sku,))
            prod=c.fetchone()
            if not prod:stop(404,"SKU_NOT_FOUND")
            c.execute("SELECT COALESCE(SUM(-delta),0) AS n FROM v3r_stock_movements WHERE sku=%s AND delta<0 AND order_id IS NOT NULL",
                      (sku,))
            depleted=int(c.fetchone()["n"])
    policy=prod["policy"]
    if not policy:stop(409,"COST_CONFIG_REQUIRED")
    amount=depleted*prod["unit_cost_xaf"] if policy=="DRINK_AUTO_TEST" else 0
    return {"sku":sku,"policy":policy,"depletedNativeUnits":depleted,
            "computedTestCogsXaf":amount,"requiresManualKitchenExpense":policy=="FOOD_MANUAL_TEST",
            "officialJournalPosted":False}

class ForwardAmendment(BaseModel):
    target_period:str
    amount_xaf:int
    channel:str
    idem:str=Field(min_length=8,max_length=100)
    note:str=Field(min_length=4,max_length=200)
    effective_at:datetime
@r.post("/finance/periods/{closed_period}/forward-amendment")
def forward_amendment(closed_period:str,body:ForwardAmendment,actor=Depends(auth)):
    who=actor_role(actor,{"REVIEWER_TEST"})
    if body.channel not in {"CASH","MTN","ORANGE","BANK"} or body.amount_xaf==0:
        stop(422,"FORWARD_AMENDMENT_INVALID")
    if body.effective_at.tzinfo is None or business_period(body.effective_at)!=body.target_period:
        stop(422,"FORWARD_AMENDMENT_TARGET_TIME_INVALID")
    ref=uuid.uuid4()
    with connect() as db:
        with db.cursor() as c:
            prev=period_get(c,closed_period)
            target=period_get(c,body.target_period)
            if prev["status"]!="CLOSED_TEST" or target["status"]!="OPEN_TEST":
                stop(409,"FORWARD_AMENDMENT_STATE_DENIED")
            try:
                c.execute("""INSERT INTO v3r_b_finance_drafts
                    (id,tenant_id,branch_id,idempotency_key,kind,channel,
                     signed_amount_xaf,effective_at,note,created_by)
                    VALUES(%s,%s,%s,%s,'FORWARD_AMENDMENT_TEST',%s,%s,%s,%s,%s)""",
                    (ref,TENANT,BRANCH,body.idem,body.channel,body.amount_xaf,
                     body.effective_at,closed_period+":"+body.note,who))
            except errors.UniqueViolation:stop(409,"DUPLICATE_FORWARD_AMENDMENT")
            finance_event(c,closed_period,"FORWARD_AMENDMENT_REFERENCED",who,str(ref))
            finance_event(c,body.target_period,"FORWARD_AMENDMENT_CREATED",who,str(ref))
        db.commit()
    return {"ref":str(ref),"originalClosedPeriod":closed_period,
            "postedOnlyInTestPeriod":body.target_period,
            "originalHistoryPreserved":True,"officialFinancePosting":False}
@r.get("/recovery/first-write-fence")
def first_write_fence(actor=Depends(auth)):
    """Conservative tenant/branch TEST fence; never authorizes destructive restore.

    Legacy stock movements have no tenant columns. Join to scoped orders where
    possible; any non-order movement is explicitly unscoped and prevents a
    no-first-write conclusion until its source ownership is reviewed.
    """
    actor_role(actor,{"REVIEWER_TEST","CLOSER_TEST"})
    with connect() as db:
        with db.cursor() as c:
            c.execute("SELECT COUNT(*) AS n FROM v3r_orders WHERE tenant_id=%s AND branch_id=%s",
                      (TENANT,BRANCH))
            orders=int(c.fetchone()["n"])
            c.execute("""SELECT COUNT(*) AS n FROM v3r_stock_movements m
                         JOIN v3r_orders o ON o.id=m.order_id
                         WHERE o.tenant_id=%s AND o.branch_id=%s""",
                      (TENANT,BRANCH))
            movements=int(c.fetchone()["n"])
            c.execute("SELECT COUNT(*) AS n FROM v3r_stock_movements WHERE order_id IS NULL")
            unattributed=int(c.fetchone()["n"])
            c.execute("SELECT COUNT(*) AS n FROM v3r_b_finance_drafts WHERE tenant_id=%s AND branch_id=%s",
                      (TENANT,BRANCH))
            drafts=int(c.fetchone()["n"])
    forward_only=orders+movements+unattributed+drafts>0
    return {"nativeOrders":orders,"nativeStockMovements":movements,
            "unattributedStockMovements":unattributed,
            "testFinanceDrafts":drafts,
            "sourceTenant":TENANT,"sourceBranch":BRANCH,
            "requiresMovementSourceReview":unattributed>0,
            "decision":"FORWARD_ONLY_PRESERVE_COMMITTED_TEST_RECORDS"
            if forward_only else "NO_TEST_FIRST_WRITE_YET",
            "neverAuthorizesRestoration":True,
            "offDeviceDisasterRecoveryProven":False,
            "productionCutoverAuthorized":False}
