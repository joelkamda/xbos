"""SOF R6: native, synthetic-only debtor-linked A/R installment TEST add-on.

No original WND customer identity; no actual debt collection, PSP calls,
Finance posting, provider finality, contacts or genuine PC5. All routes
require bounded local synthetic TEST sessions and 920002/1 native PG17.
Each obligation references exactly one existing native TEST order; never
creates a second sale or copies a historical WND debtor.
"""
from __future__ import annotations
from datetime import date
from uuid import UUID,uuid4
from fastapi import APIRouter,Depends,Query
from pydantic import BaseModel,Field
from psycopg import errors
from .api import auth,TENANT,BRANCH
from .seed import connect
from .v24_native_api import actor_role,stop

ar=APIRouter(prefix="/api/v3/v24/sof/ar",tags=["SOF-R6-native-test-ar"])
class DebtorInput(BaseModel):
    display_name:str=Field(min_length=2,max_length=100)
    source_ref:str|None=Field(default=None,min_length=8,max_length=100)
    tenant_id:int=Field(default=TENANT,strict=True)
    branch_id:int=Field(default=BRANCH,strict=True)

class LinkInput(BaseModel):
    debtor_id:UUID
    order_id:UUID
    due_date:date|None=None
    tenant_id:int=Field(default=TENANT,strict=True)
    branch_id:int=Field(default=BRANCH,strict=True)

class PaymentInput(BaseModel):
    idem:str=Field(min_length=8,max_length=100,pattern=r"^[A-Za-z0-9._:-]+$")
    amount_xaf:int=Field(gt=0,le=100000000,strict=True)
    channel:str
    expected_revision:int=Field(ge=1,strict=True)
    tenant_id:int=Field(default=TENANT,strict=True)
    branch_id:int=Field(default=BRANCH,strict=True)

def _scope(data):
    if (data.tenant_id,data.branch_id)!=(TENANT,BRANCH):
        stop(403,"SOF_AR_TENANT_BRANCH_DENIED")

def _meta():
    return {"grade":"SYNTHETIC_TEST_ONLY", "tenantId":TENANT,"branchId":BRANCH,
            "realCustomer":False,"genuinePC5":False,"financePosted":False,
            "actualCollection":False,"providerSettled":False,
            "customerPaid":False,"externalEffects":False}

def _debtor(c,debtor_id,lock=False):
    c.execute("""SELECT * FROM v24_ar_debtors
                 WHERE tenant_id=%s AND branch_id=%s AND id=%s """+
              (" FOR UPDATE" if lock else ""),
              (TENANT,BRANCH,debtor_id))
    d=c.fetchone()
    if not d:stop(404,"SOF_AR_DEBTOR_NOT_FOUND")
    return d

def _obligation(c,obligation_id,lock=False):
    c.execute("""SELECT * FROM v24_ar_obligations
                 WHERE tenant_id=%s AND branch_id=%s AND id=%s """+
              (" FOR UPDATE" if lock else ""),
              (TENANT,BRANCH,obligation_id))
    row=c.fetchone()
    if not row:stop(404,"SOF_AR_OBLIGATION_NOT_FOUND")
    return row

def _tender_totals(c,order_id):
    c.execute("""SELECT status,COALESCE(SUM(amount_xaf),0)::bigint AS amount
                 FROM v24_tender_intents WHERE order_id=%s
                 GROUP BY status""",(order_id,))
    t={x["status"]:int(x["amount"]) for x in c.fetchall()}
    return t.get("CASH_RECEIVED_TEST",0),t.get("PROVIDER_PENDING_TEST",0)


def _amounts(c,obligation_id):
    # Provider intents already attached to the order before debtor linkage
    # are still reservations, NOT collections. Count them exactly once
    # alongside any later A/R provider-pending intentions.
    c.execute("""SELECT order_id,provider_pending_at_link_xaf
                 FROM v24_ar_obligations
                 WHERE tenant_id=%s AND branch_id=%s AND id=%s""",
              (TENANT,BRANCH,obligation_id))
    root=c.fetchone()
    if not root:stop(404,"SOF_AR_OBLIGATION_NOT_FOUND")
    original_pending=int(root["provider_pending_at_link_xaf"])
    c.execute("""SELECT state, COALESCE(SUM(amount_xaf),0)::bigint AS total
                 FROM v24_ar_collections
                 WHERE tenant_id=%s AND branch_id=%s AND obligation_id=%s
                 GROUP BY state""",(TENANT,BRANCH,obligation_id))
    states={r["state"]:int(r["total"]) for r in c.fetchall()}
    return (states.get("CASH_RECEIVED_TEST",0),
            states.get("PROVIDER_PENDING_TEST",0)+original_pending)

@ar.post("/debtors")
def create_debtor(body:DebtorInput,actor=Depends(auth)):
    who=actor_role(actor,{"MERCHANT_TEST"})
    _scope(body)
    name=body.display_name.strip()
    if len(name)<2:stop(422,"SOF_AR_DEBTOR_NAME_INVALID")
    ident=uuid4()
    try:
        with connect() as db:
            with db.cursor() as c:
                c.execute("""INSERT INTO v24_ar_debtors
                     (id,tenant_id,branch_id,display_name,source_ref,created_by)
                     VALUES(%s,%s,%s,%s,%s,%s)""",
                     (ident,TENANT,BRANCH,name,body.source_ref,who))
                c.execute("""INSERT INTO v24_ar_audit
                     (tenant_id,branch_id,debtor_id,action,actor)
                     VALUES(%s,%s,%s,'CREATE_DEBTOR_TEST',%s)""",
                     (TENANT,BRANCH,ident,who))
            db.commit()
    except errors.UniqueViolation:
        stop(409,"SOF_AR_DUPLICATE_SOURCE_DEBTOR_NO_MERGE")
    return {**_meta(),"debtorId":str(ident),"displayName":name,
            "revision":1,"sourceVerified":False,
            "status":"TEST_DEBTOR_UNVERIFIED_NO_HISTORICAL_MERGE"}

@ar.get("/debtors")
def list_debtors(q:str="",limit:int=Query(50,ge=1,le=100),
                 tenant_id:int=TENANT,branch_id:int=BRANCH,
                 actor=Depends(auth)):
    actor_role(actor,{"MERCHANT_TEST","REVIEWER_TEST","CASHIER_TEST"})
    if (tenant_id,branch_id)!=(TENANT,BRANCH):stop(403,"SOF_AR_TENANT_BRANCH_DENIED")
    if len(q)>100:stop(422,"SOF_AR_SEARCH_TOO_LONG")
    with connect() as db:
        with db.cursor() as c:
            c.execute("""SELECT id::text AS debtor_id,display_name,source_ref,
                         revision,source_verified
                         FROM v24_ar_debtors
                         WHERE tenant_id=%s AND branch_id=%s
                         AND display_name ILIKE %s ORDER BY display_name,id LIMIT %s""",
                         (TENANT,BRANCH,"%"+q.replace("%",r"\%").replace("_",r"\_")+"%",limit))
            rows=c.fetchall()
    return {**_meta(),"rows":rows,"status":"TEST_DEBTORS_SEARCH_NOT_HISTORICAL_WND"}

@ar.post("/obligations")
def link_unpaid_order(body:LinkInput,actor=Depends(auth)):
    who=actor_role(actor,{"MERCHANT_TEST"})
    _scope(body)
    ident=uuid4()
    try:
        with connect() as db:
            with db.cursor() as c:
                _debtor(c,body.debtor_id)
                c.execute("""SELECT id,amount_xaf,status FROM v3r_orders
                             WHERE id=%s AND tenant_id=%s AND branch_id=%s
                             FOR UPDATE""",(body.order_id,TENANT,BRANCH))
                order=c.fetchone()
                if not order:stop(404,"SOF_AR_ORDER_NOT_FOUND")
                if order["status"]!="UNPAID_TEST":
                    stop(409,"SOF_AR_ALREADY_SETTLED_ORDER")
                c.execute("SELECT amount_xaf FROM v24_order_discounts WHERE order_id=%s",
                          (body.order_id,))
                dr=c.fetchone()
                discount=int(dr["amount_xaf"]) if dr else 0
                c.execute("""SELECT status,COALESCE(SUM(amount_xaf),0)::bigint AS xaf
                             FROM v24_tender_intents WHERE order_id=%s
                             GROUP BY status""",(body.order_id,))
                tenders={x["status"]:int(x["xaf"]) for x in c.fetchall()}
                cash=tenders.get("CASH_RECEIVED_TEST",0)
                pending=tenders.get("PROVIDER_PENDING_TEST",0)
                due=int(order["amount_xaf"])-discount-cash
                if due<=0:stop(409,"SOF_AR_NO_UNPAID_BALANCE")
                if pending>due:stop(409,"SOF_AR_PROVIDER_PENDING_EXCEEDS_DUE")
                c.execute("""INSERT INTO v24_ar_obligations
                    (id,tenant_id,branch_id,order_id,debtor_id,original_due_xaf,
                     cash_tender_at_link_xaf,provider_pending_at_link_xaf,
                     due_date,prepared_by)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (ident,TENANT,BRANCH,body.order_id,body.debtor_id,due,
                     cash,pending,body.due_date,who))
                c.execute("""INSERT INTO v24_ar_audit
                    (tenant_id,branch_id,debtor_id,obligation_id,action,actor)
                    VALUES(%s,%s,%s,%s,'LINK_ORDER_TEST',%s)""",
                    (TENANT,BRANCH,body.debtor_id,ident,who))
            db.commit()
    except errors.UniqueViolation:
        stop(409,"SOF_AR_ORDER_ALREADY_LINKED_ONCE")
    return {**_meta(),"obligationId":str(ident),"debtorId":str(body.debtor_id),
            "orderId":str(body.order_id),"sourceGrossXaf":int(order["amount_xaf"]),
            "discountXaf":discount,"alreadyCashTestXaf":cash,
            "providerPendingTestXaf":pending,"originalDueXaf":due,
            "revision":1,"status":"TEST_ORDER_DEBT_LINKED_NOT_A_SECOND_SALE"}

@ar.post("/obligations/{obligation_id}/collections")
def new_collection(obligation_id:UUID,body:PaymentInput,actor=Depends(auth)):
    who=actor_role(actor,{"CASHIER_TEST"})
    _scope(body)
    if body.channel not in {"CASH","MTN","ORANGE","BANK"}:
        stop(422,"SOF_AR_CHANNEL_INVALID")
    pending=(body.channel!="CASH")
    state="PROVIDER_PENDING_TEST" if pending else "CASH_RECEIVED_TEST"
    ident=uuid4()
    try:
        with connect() as db:
            with db.cursor() as c:
                row=_obligation(c,obligation_id,lock=True)
                current_cash,current_pending=_tender_totals(c,row["order_id"])
                if (current_cash,current_pending)!=(int(row["cash_tender_at_link_xaf"]),
                                                      int(row["provider_pending_at_link_xaf"])):
                    stop(409,"SOF_AR_SOURCE_TENDER_CHANGED_REVIEW_REQUIRED")
                if row["revision"]!=body.expected_revision:
                    stop(409,"SOF_AR_STALE_OBLIGATION_REVISION")
                c.execute("""SELECT 1 FROM v24_ar_collections
                             WHERE tenant_id=%s AND branch_id=%s AND obligation_id=%s
                               AND idem=%s""",
                          (TENANT,BRANCH,obligation_id,body.idem))
                if c.fetchone():stop(409,"SOF_AR_DUPLICATE_COLLECTION_NO_NEW_EFFECT")
                cash,queued=_amounts(c,obligation_id)
                if cash+queued+body.amount_xaf>int(row["original_due_xaf"]):
                    stop(409,"SOF_AR_OVERALLOCATION_DENIED")
                c.execute("""INSERT INTO v24_ar_collections
                    (id,tenant_id,branch_id,obligation_id,idem,amount_xaf,
                     channel,state,created_by)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (ident,TENANT,BRANCH,obligation_id,body.idem,
                     body.amount_xaf,body.channel,state,who))
                c.execute("""UPDATE v24_ar_obligations
                             SET revision=revision+1 WHERE id=%s""",(obligation_id,))
                c.execute("""INSERT INTO v24_ar_audit
                    (tenant_id,branch_id,debtor_id,obligation_id,collection_id,action,actor)
                    VALUES(%s,%s,%s,%s,%s,'ALLOCATE_COLLECTION_TEST',%s)""",
                    (TENANT,BRANCH,row["debtor_id"],obligation_id,ident,who))
            db.commit()
    except errors.UniqueViolation:
        stop(409,"SOF_AR_DUPLICATE_COLLECTION_NO_NEW_EFFECT")
    return {**_meta(),"collectionId":str(ident),"obligationId":str(obligation_id),
            "state":state,"cashTestAllocatedXaf":body.amount_xaf if not pending else 0,
            "providerPendingXaf":body.amount_xaf if pending else 0,
            "obligationRevision":body.expected_revision+1,
            "status":"TEST_COLLECTION_TRACE_NOT_FINANCE_POST_OR_PSP_SETTLEMENT"}

@ar.get("/obligations/{obligation_id}")
def obligation_detail(obligation_id:UUID,tenant_id:int=TENANT,branch_id:int=BRANCH,
                      actor=Depends(auth)):
    actor_role(actor,{"MERCHANT_TEST","REVIEWER_TEST","CASHIER_TEST","CLOSER_TEST"})
    if (tenant_id,branch_id)!=(TENANT,BRANCH):stop(403,"SOF_AR_TENANT_BRANCH_DENIED")
    with connect() as db:
        with db.cursor() as c:
            row=_obligation(c,obligation_id)
            debtor=_debtor(c,row["debtor_id"])
            cash,pending=_amounts(c,obligation_id)
            live_cash,live_pending=_tender_totals(c,row["order_id"])
            source_drift=(live_cash,live_pending)!=(int(row["cash_tender_at_link_xaf"]),
                                                    int(row["provider_pending_at_link_xaf"]))
            c.execute("""SELECT id::text AS ref,idem,amount_xaf,channel,state,
                         created_at,created_by
                         FROM v24_ar_collections WHERE obligation_id=%s
                         ORDER BY created_at,id""",(obligation_id,))
            history=c.fetchall()
    opened=int(row["original_due_xaf"])
    return {**_meta(),"obligationId":str(obligation_id),
            "sourceOrderId":str(row["order_id"]), "debtorId":str(row["debtor_id"]),
            "debtorName":debtor["display_name"],"dueDate":row["due_date"],
            "revision":int(row["revision"]),"originalDueXaf":opened,
            "cashTestAllocatedXaf":cash,"providerPendingXaf":pending,
            "outstandingXaf":opened-cash,
            "unreservedXaf":opened-cash-pending,
            "collectionHistory":history,
            "status":"SOF_AR_SOURCE_TENDER_DRIFT_HOLD" if source_drift
                     else "TEST_AR_OPEN_SOURCE_ONLY",
            "sourceTenderChangedAfterLink":source_drift,
            "sourceTenderReviewRequired":source_drift,
            "actualHistoricalWndParity":False}

@ar.get("/debtors/{debtor_id}/statement")
def debtor_statement(debtor_id:UUID,tenant_id:int=TENANT,branch_id:int=BRANCH,
                     actor=Depends(auth)):
    actor_role(actor,{"MERCHANT_TEST","REVIEWER_TEST","CASHIER_TEST","CLOSER_TEST"})
    if (tenant_id,branch_id)!=(TENANT,BRANCH):stop(403,"SOF_AR_TENANT_BRANCH_DENIED")
    with connect() as db:
        with db.cursor() as c:
            debtor=_debtor(c,debtor_id)
            c.execute("""SELECT id::text AS obligation_id,order_id::text,
                         original_due_xaf,cash_tender_at_link_xaf,
                         provider_pending_at_link_xaf,due_date,revision
                         FROM v24_ar_obligations WHERE tenant_id=%s
                         AND branch_id=%s AND debtor_id=%s ORDER BY created_at,id""",
                         (TENANT,BRANCH,debtor_id))
            rows=c.fetchall()
            obligations=[]
            for row in rows:
                cash,pending=_amounts(c,UUID(row["obligation_id"]))
                live=_tender_totals(c,UUID(row["order_id"]))
                snapshot=(int(row["cash_tender_at_link_xaf"]),
                          int(row["provider_pending_at_link_xaf"]))
                opened=int(row["original_due_xaf"])
                obligations.append({**row,"cashTestAllocatedXaf":cash,
                                    "providerPendingXaf":pending,
                                    "sourceTenderChangedAfterLink":live!=snapshot,
                                    "outstandingXaf":opened-cash})
    total=sum(x["outstandingXaf"] for x in obligations)
    return {**_meta(),"debtorId":str(debtor_id),"displayName":debtor["display_name"],
            "sourceVerified":False,"obligations":obligations,
            "outstandingXaf":total,"historicalWndAccountMatch":False,
            "status":"SOF_AR_TENDER_DRIFT_REVIEW_REQUIRED" if any(
                x["sourceTenderChangedAfterLink"] for x in obligations)
                     else "TEST_DEBTOR_STATEMENT_NOT_CANONICAL_AR"}

@ar.get("/audit")
def ar_audit(tenant_id:int=TENANT,branch_id:int=BRANCH,
             limit:int=Query(100,ge=1,le=500),actor=Depends(auth)):
    actor_role(actor,{"MERCHANT_TEST","REVIEWER_TEST","CLOSER_TEST"})
    if (tenant_id,branch_id)!=(TENANT,BRANCH):stop(403,"SOF_AR_TENANT_BRANCH_DENIED")
    with connect() as db:
        with db.cursor() as c:
            c.execute("""SELECT seq,debtor_id::text,obligation_id::text,collection_id::text,
                         action,actor,at FROM v24_ar_audit
                         WHERE tenant_id=%s AND branch_id=%s
                         ORDER BY seq LIMIT %s""",(TENANT,BRANCH,limit))
            audit=c.fetchall()
    return {**_meta(),"audit":audit,"officialAccountAudit":False}
