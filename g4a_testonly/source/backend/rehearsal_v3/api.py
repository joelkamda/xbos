"""Real PostgreSQL-backed XCOMP WND V3 FUNCTIONAL TEST adapter.
Not production XBOS startup, not PC5, not WND/Twilio/PSP. Only separate local
TEST database at 127.0.0.1:55438, and loopback HTTP on Pavilion.
Real SQL transaction semantics; all money/status records explicitly TEST.
"""
from __future__ import annotations
import base64
from datetime import datetime, timedelta, timezone
import hashlib, hmac, json, secrets, uuid
from typing import Literal
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware
from psycopg.rows import dict_row
from psycopg import errors
from .seed import connect, config, LAB
from restaurant.d7_wnd_cashier_kitchen_receipt import CashierLine, CashierSource, preview_cashier
from .wnd_explicit_catalog import WndExplicitProduct, require_activation, review

app=FastAPI(title="XCOMP WND V3 Isolated Real Database Rehearsal",
            description="Dedicated TEST persistence, not genuine PC5/G3 admission")
app.add_middleware(TrustedHostMiddleware,
                   allowed_hosts=["127.0.0.1","localhost","testserver"])
app.add_middleware(CORSMiddleware,allow_origins=[
    "http://127.0.0.1:5178","http://localhost:5178"
],allow_credentials=False,allow_methods=["GET","POST"],allow_headers=[
    "Content-Type","X-Rehearsal-Token"])
DB_LABEL="V24_SYNTHETIC_NATIVE_PG17_TEST_ONLY"
TENANT=920002
BRANCH=1

def fail(code:int, reason:str):
    raise HTTPException(status_code=code,detail=reason)

def b64(data:bytes)->str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")

def unb64(data:str)->bytes:
    return base64.urlsafe_b64decode(data+"="*(-len(data)%4))

def issue(session_id:uuid.UUID, expires:int)->str:
    payload=json.dumps({"sid":str(session_id),"exp":expires,"grade":"REHEARSAL_ONLY"},
                       sort_keys=True,separators=(",",":")).encode()
    sig=hmac.new(bytes.fromhex(config()["session_hmac_key_hex"]),payload,hashlib.sha256).digest()
    return b64(payload)+"."+b64(sig)

def auth(x_rehearsal_token:str|None=Header(default=None)):
    if not x_rehearsal_token or len(x_rehearsal_token)>1400:
        fail(401,"REHEARSAL_SESSION_REQUIRED")
    try:
        a,b=x_rehearsal_token.split(".")
        payload=unb64(a)
        expected=hmac.new(bytes.fromhex(config()["session_hmac_key_hex"]),payload,hashlib.sha256).digest()
        if not hmac.compare_digest(expected,unb64(b)):
            fail(401,"SESSION_SIGNATURE_INVALID")
        data=json.loads(payload)
        if data.get("grade")!="REHEARSAL_ONLY":
            fail(401,"NOT_REHEARSAL_AUTHORITY")
        sid=uuid.UUID(data["sid"])
        exp=data["exp"]
        if type(exp) is not int or exp<=int(datetime.now(timezone.utc).timestamp()):
            fail(401,"SESSION_EXPIRED")
    except HTTPException: raise
    except Exception:fail(401,"SESSION_INVALID")
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT username,expires_at,revoked_at FROM v3r_sessions WHERE id=%s",(sid,))
            r=cur.fetchone()
            if not r or r["revoked_at"] is not None or r["expires_at"]<=datetime.now(timezone.utc):
                fail(401,"SESSION_REVOKED_OR_EXPIRED")
    return {"username":r["username"],"sid":sid,"scope":"LOCAL_TEST_ONLY"}

class LoginBody(BaseModel):
    username:str=Field(min_length=1,max_length=40)
    password:str=Field(min_length=1,max_length=200)

class OrderLine(BaseModel):
    sku:str=Field(min_length=1,max_length=80,pattern=r"^[A-Za-z0-9-]+$")
    quantity:int=Field(ge=1,le=20)

class OrderBody(BaseModel):
    idempotency_key:str=Field(min_length=8,max_length=100,pattern=r"^[A-Za-z0-9._:-]+$")
    zone:Literal["MAIN","VIP","BAR"]
    lines:list[OrderLine]=Field(min_length=1,max_length=15)

class ProductBody(BaseModel):
    name:str=Field(min_length=2,max_length=90)
    category:str=Field(min_length=2,max_length=50)
    family:Literal["bar","kitchen","other"]
    base_xaf:int=Field(ge=100,le=500000)
    stock_qty:int|None=Field(default=None,ge=0,le=100000)

@app.get("/api/v3/health")
def health():
    with connect() as conn:
        with conn.cursor() as c:
            c.execute("SELECT current_database() AS db,current_setting('port') AS port")
            row=c.fetchone()
    return {"status":"REAL_POSTGRES_TEST_READY","database":row["db"],"port":row["port"],
            "grade":DB_LABEL,"pc5Admitted":False,"g3Admitted":False,"g4Released":False,
            "noProductionData":True,"externalPaymentsDisabled":True}

@app.post("/api/v3/session")
def login(body:LoginBody):
    with connect() as conn:
        with conn.cursor() as c:
            c.execute("SELECT salt,hash,role FROM v3r_operator WHERE username=%s",(body.username,))
            row=c.fetchone()
            if not row:fail(401,"INVALID_TEST_LOGIN")
            candidate=hashlib.pbkdf2_hmac("sha256",body.password.encode(),
                                         bytes.fromhex(row["salt"]),185000).hex()
            if not hmac.compare_digest(candidate,row["hash"]):
                fail(401,"INVALID_TEST_LOGIN")
            sid=uuid.uuid4()
            expiry=datetime.now(timezone.utc)+timedelta(minutes=30)
            c.execute("INSERT INTO v3r_sessions(id,expires_at,username) VALUES(%s,%s,%s)",
                      (sid,expiry,body.username))
        conn.commit()
    return {"token":issue(sid,int(expiry.timestamp())),"expiresAt":expiry.isoformat(),
            "role":row["role"],"grade":DB_LABEL,"pc5":False}

@app.post("/api/v3/session/revoke")
def revoke(session=Depends(auth)):
    with connect() as conn:
        with conn.cursor() as c:
            c.execute("UPDATE v3r_sessions SET revoked_at=NOW() WHERE id=%s AND revoked_at IS NULL",
                      (session["sid"],))
        conn.commit()
    return {"revoked":True,"grade":DB_LABEL}

@app.get("/api/v3/catalog")
def catalog(zone:Literal["MAIN","VIP","BAR"]="MAIN",session=Depends(auth)):
    with connect() as conn:
        with conn.cursor() as c:
            c.execute("""SELECT p.sku,p.name,p.category,p.family,p.stock_qty,
                         p.source_revision,pr.amount_xaf,pr.price_revision
                         FROM v3r_products p JOIN v3r_prices pr ON pr.sku=p.sku
                         WHERE pr.zone=%s AND p.active ORDER BY p.category,p.name""",(zone,))
            rows=c.fetchall()
    return {"zone":zone,"tenant":TENANT,"branch":BRANCH,
            "dataGrade":"SYNTHETIC_V24_TEST_PRODUCTS_NO_PII",
            "items":rows,"count":len(rows)}

@app.post("/api/v3/products")
def add_product(body:ProductBody,session=Depends(auth)):
    sku="TEST-NEW-"+uuid.uuid4().hex[:12].upper()
    category=body.category.strip().upper()
    name=body.name.strip()
    with connect() as conn:
        with conn.cursor() as c:
            c.execute("""INSERT INTO v3r_products(sku,name,category,family,stock_qty)
                         VALUES(%s,%s,%s,%s,%s)""",
                      (sku,name,category,body.family,body.stock_qty))
            for zone,mult in [("MAIN",100),("VIP",125),("BAR",110)]:
                price=((body.base_xaf*mult+5000)//10000)*100
                c.execute("INSERT INTO v3r_prices(sku,zone,amount_xaf) VALUES(%s,%s,%s)",
                          (sku,zone,price))
        conn.commit()
    return {"sku":sku,"name":name,"revision":1,"persisted":True,"grade":DB_LABEL}

@app.get("/api/v3/orders")
def orders(session=Depends(auth)):
    with connect() as conn:
        with conn.cursor() as c:
            c.execute("""SELECT o.id::text,o.zone,o.status,o.amount_xaf,o.created_at,
                         COALESCE(json_agg(json_build_object(
                           'sku',l.sku,'quantity',l.quantity,'unit_xaf',l.unit_xaf,
                           'line_xaf',l.line_xaf)) FILTER(WHERE l.sku IS NOT NULL),'[]'::json) AS lines
                         FROM v3r_orders o LEFT JOIN v3r_order_lines l ON o.id=l.order_id
                         GROUP BY o.id ORDER BY o.created_at DESC LIMIT 100""")
            rows=c.fetchall()
    return {"orders":rows,"persisted":True,"grade":DB_LABEL}

@app.post("/api/v3/orders")
def place_order(body:OrderBody,session=Depends(auth)):
    if len({x.sku for x in body.lines})!=len(body.lines):
        fail(422,"DUPLICATE_SKU_DENIED")
    order_id=uuid.uuid4()
    receipts=[]
    try:
        with connect() as conn:
            with conn.cursor() as c:
                c.execute("SELECT id FROM v3r_orders WHERE idempotency_key=%s",(body.idempotency_key,))
                prior=c.fetchone()
                if prior:
                    return {"orderId":str(prior["id"]),"replayed":True,"grade":DB_LABEL}
                total=0
                for line in sorted(body.lines,key=lambda x:x.sku):
                    c.execute("""SELECT p.name,p.family,p.stock_qty,pr.amount_xaf
                                 FROM v3r_products p JOIN v3r_prices pr ON p.sku=pr.sku
                                 WHERE p.sku=%s AND pr.zone=%s AND p.active
                                 FOR UPDATE OF p""",(line.sku,body.zone))
                    prod=c.fetchone()
                    if not prod:fail(422,"UNKNOWN_OR_INACTIVE_SKU")
                    if prod["stock_qty"] is not None and prod["stock_qty"]<line.quantity:
                        fail(409,"NEGATIVE_STOCK_BALANCE_DENIED")
                    unit=prod["amount_xaf"]
                    amount=unit*line.quantity
                    total+=amount
                    if total>5_000_000:fail(422,"ORDER_TOTAL_LIMIT")
                    receipts.append((line.sku,prod["name"],prod["family"],
                                     line.quantity,unit,prod["stock_qty"]))
                c.execute("""INSERT INTO v3r_orders(id,idempotency_key,zone,amount_xaf)
                             VALUES(%s,%s,%s,%s)""",
                          (order_id,body.idempotency_key,body.zone,total))
                for sku,name,family,qty,unit,stock in receipts:
                    c.execute("""INSERT INTO v3r_order_lines(order_id,sku,quantity,unit_xaf,line_xaf)
                                 VALUES(%s,%s,%s,%s,%s)""",(order_id,sku,qty,unit,qty*unit))
                    if stock is not None:
                        c.execute("UPDATE v3r_products SET stock_qty=stock_qty-%s WHERE sku=%s RETURNING stock_qty",(qty,sku))
                        after=c.fetchone()["stock_qty"]
                        c.execute("""INSERT INTO v3r_stock_movements(id,sku,order_id,delta,quantity_after)
                                     VALUES(%s,%s,%s,%s,%s)""",(uuid.uuid4(),sku,order_id,-qty,after))
                    if family=="kitchen":
                        c.execute("""INSERT INTO v3r_kitchen_tickets(id,order_id,sku,quantity)
                                     VALUES(%s,%s,%s,%s)""",(uuid.uuid4(),order_id,sku,qty))
                c.execute("""INSERT INTO v3r_finance_events(id,order_id,kind,amount_xaf)
                             VALUES(%s,%s,'RECEIVABLE_TEST',%s)""",
                          (uuid.uuid4(),order_id,total))
            conn.commit()
    except errors.UniqueViolation:
        fail(409,"CONCURRENT_IDEMPOTENCY_CONFLICT")
    source=CashierSource(tenant_id=TENANT,branch_id=BRANCH,order_ref=str(order_id),
                         receipt_no="TEST-"+str(order_id)[:8],cashier_ref="rehearsal-operator",
                         staff_permission=True,kitchen_permission=True,
                         NIU="TEST-ONLY-NO-TAX-ID",
                         lines=tuple(CashierLine(sku,n,f,qty,unit,sku) for sku,n,f,qty,unit,_ in receipts))
    domain=preview_cashier(source=source)
    assert domain.total_xaf==total
    return {"orderId":str(order_id),"totalXaf":total,"zone":body.zone,
            "persisted":True,"receiptPreview":list(domain.receipt_lines),
            "kitchenSkus":list(domain.kitchen_skus),"financeTestOnly":True,
            "paid":False,"providerCalled":False,"grade":DB_LABEL}

@app.get("/api/v3/kitchen")
def kitchen(session=Depends(auth)):
    with connect() as conn:
        with conn.cursor() as c:
            c.execute("""SELECT t.id::text,t.order_id::text,t.sku,t.quantity,t.status,p.name
                         FROM v3r_kitchen_tickets t JOIN v3r_products p ON p.sku=t.sku
                         ORDER BY t.status,t.id LIMIT 200""")
            rows=c.fetchall()
    return {"tickets":rows,"printerConnected":False,"grade":DB_LABEL}

@app.post("/api/v3/kitchen/{ticket_id}/ready")
def ready(ticket_id:uuid.UUID,session=Depends(auth)):
    with connect() as conn:
        with conn.cursor() as c:
            c.execute("""UPDATE v3r_kitchen_tickets SET status='READY'
                         WHERE id=%s AND status='PENDING' RETURNING id""",(ticket_id,))
            row=c.fetchone()
            if not row:fail(409,"TICKET_ABSENT_OR_ALREADY_READY")
        conn.commit()
    return {"ready":True,"persisted":True,"printed":False,"grade":DB_LABEL}

@app.post("/api/v3/orders/{order_id}/cash-test")
def settle(order_id:uuid.UUID,session=Depends(auth)):
    with connect() as conn:
        with conn.cursor() as c:
            c.execute("""UPDATE v3r_orders SET status='CASH_SETTLED_TEST'
                         WHERE id=%s AND status='UNPAID_TEST'
                         RETURNING amount_xaf""",(order_id,))
            row=c.fetchone()
            if not row:fail(409,"ORDER_ABSENT_OR_SETTLED")
            c.execute("""INSERT INTO v3r_finance_events(id,order_id,kind,amount_xaf)
                         VALUES(%s,%s,'CASH_RECEIPT_TEST',%s)""",
                      (uuid.uuid4(),order_id,row["amount_xaf"]))
        conn.commit()
    return {"cashTestPosted":True,"amountXaf":row["amount_xaf"],
            "noActualMoney":True,"noProviderCalls":True,"grade":DB_LABEL}

@app.get("/api/v3/inventory")
def inventory(session=Depends(auth)):
    with connect() as conn:
        with conn.cursor() as c:
            c.execute("""SELECT sku,name,category,family,stock_qty,
                         source_revision FROM v3r_products ORDER BY category,name LIMIT 500""")
            rows=c.fetchall()
            c.execute("SELECT COUNT(*) AS n FROM v3r_stock_movements")
            movements=c.fetchone()["n"]
    return {"items":rows,"stockMovements":movements,"nullMeansWithheld":True,"grade":DB_LABEL}

@app.get("/api/v3/finance")
def finance(session=Depends(auth)):
    with connect() as conn:
        with conn.cursor() as c:
            c.execute("""SELECT f.id::text,f.order_id::text,f.kind,f.amount_xaf,f.created_at
                         FROM v3r_finance_events f ORDER BY created_at DESC LIMIT 100""")
            rows=c.fetchall()
            c.execute("""SELECT COALESCE(SUM(amount_xaf),0) AS total FROM v3r_orders
                         WHERE status='UNPAID_TEST'""")
            outstanding=c.fetchone()["total"]
            c.execute("""SELECT COALESCE(SUM(amount_xaf),0) AS total FROM v3r_orders
                         WHERE status='CASH_SETTLED_TEST'""")
            cash=c.fetchone()["total"]
    return {"rows":rows,"receivablesOpenXaf":int(outstanding),"cashTestXaf":int(cash),
            "realPayment":False,"realFinance":False,"grade":DB_LABEL}

@app.post("/api/v3/products/source-priced/preview")
def preview_source_priced_product(
    body:WndExplicitProduct, session=Depends(auth)
):
    """Authenticates the limited TEST session; previews, never writes."""
    return review(body)

@app.post("/api/v3/products/source-priced/activate-test")
def activate_explicit_source_prices(
    body:WndExplicitProduct, session=Depends(auth)
):
    """Dedicated isolated TEST operation, not PC5 product publication.

    Each zone must carry its own explicitly entered nonpersonal price.
    No WND row is loaded, guessed, defaulted or certified by this route.
    """
    audited=require_activation(body)
    sku="TEST-EXPLICIT-"+uuid.uuid4().hex[:12].upper()
    try:
        with connect() as conn:
            with conn.cursor() as c:
                c.execute(
                    """INSERT INTO v3r_products(
                         sku,name,category,family,unit,stock_qty
                       ) VALUES(%s,%s,%s,%s,%s,%s)""",
                    (sku,body.name,body.category.strip().upper(),
                     body.family,body.unit_code,
                     body.stock_qty if body.stock_tracked else None)
                )
                for price in audited["priceRows"]:
                    c.execute(
                        """INSERT INTO v3r_prices(
                             sku,zone,amount_xaf,price_revision
                           ) VALUES(%s,%s,%s,%s)""",
                        (sku,price["zone"],price["amount_xaf"],
                         price["price_revision"])
                    )
            conn.commit()
    except errors.UniqueViolation:
        fail(409,"TEST_EXPLICIT_PRODUCT_SKU_CONFLICT")
    return {
        "sku":sku,"name":body.name,
        "persisted":True,"zonePrices":audited["priceRows"],
        "dataGrade":"SYNTHETIC_NONPERSONAL_TEST_ONLY",
        "realWndSourceRows":0,"derivedPriceMultipliers":False,
        "testActivationOnly":True,"genuinePc5":False,
        "realCatalogPublished":False,
        "realFinanceEffects":0,"realPaymentEffects":0,
        "g3Admitted":False,"g4Released":False
    }

@app.get("/api/v3/summary")
def summary(session=Depends(auth)):
    with connect() as conn:
        with conn.cursor() as c:
            c.execute("SELECT COUNT(*) AS n FROM v3r_products WHERE active")
            products=c.fetchone()["n"]
            c.execute("SELECT COUNT(*) AS n FROM v3r_orders")
            orders=c.fetchone()["n"]
            c.execute("SELECT COUNT(*) AS n FROM v3r_kitchen_tickets WHERE status='PENDING'")
            pending=c.fetchone()["n"]
    return {"products":products,"orders":orders,"kitchenPending":pending,"persisted":True,
            "grade":DB_LABEL,"G3":"NOT_ADMITTED","G4":"DENIED"}
