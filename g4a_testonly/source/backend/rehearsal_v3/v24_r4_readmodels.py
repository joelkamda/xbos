"""R4 live native TEST read models: Douala daily/shift Finance and inventory as-of.
Only native PG17 TEST tables. Returns separated categories, NEVER official balances.
"""
from datetime import date,datetime,time,timedelta,timezone
from zoneinfo import ZoneInfo
from fastapi import APIRouter,Depends,Query
from .api import auth,TENANT,BRANCH
from .seed import connect
from .v24_native_api import actor_role,stop
r4=APIRouter(prefix="/api/v3/v24/r4",tags=["native-test-finance-inventory-read-models"])
LOCAL=ZoneInfo("Africa/Douala")
def windows(day:date,shift:str):
    day_start=datetime.combine(day,time(8,0),tzinfo=LOCAL)
    if shift=="DAY":return day_start,day_start+timedelta(hours=10)
    if shift=="NIGHT":return day_start+timedelta(hours=10),day_start+timedelta(days=1)
    if shift=="ALL":return day_start,day_start+timedelta(days=1)
    stop(422,"SHIFT_INVALID")
def utc(v:datetime):return v.astimezone(timezone.utc).isoformat()
@r4.get("/daily")
def daily(day:date,shift:str=Query("ALL"),actor=Depends(auth)):
    actor_role(actor,{"MERCHANT_TEST","REVIEWER_TEST","CLOSER_TEST"})
    start,end=windows(day,shift)
    with connect() as db:
        with db.cursor() as c:
            c.execute("""SELECT COUNT(*)::int AS n,COALESCE(SUM(amount_xaf),0)::bigint AS gross
                 FROM v3r_orders WHERE tenant_id=%s AND branch_id=%s
                   AND created_at >= %s AND created_at < %s""",
                   (TENANT,BRANCH,start,end))
            sales=c.fetchone()
            c.execute("""SELECT COUNT(*)::int AS n,COALESCE(SUM(d.amount_xaf),0)::bigint AS discount
                 FROM v24_order_discounts d JOIN v3r_orders o ON o.id=d.order_id
                 WHERE o.tenant_id=%s AND o.branch_id=%s
                 AND o.created_at >= %s AND o.created_at < %s""",
                  (TENANT,BRANCH,start,end))
            disc=c.fetchone()
            c.execute("""SELECT t.channel,t.status,COUNT(*)::int AS n,
                   COALESCE(SUM(t.amount_xaf),0)::bigint AS amount
                 FROM v24_tender_intents t JOIN v3r_orders o ON o.id=t.order_id
                 WHERE o.tenant_id=%s AND o.branch_id=%s
                   AND t.created_at >= %s AND t.created_at < %s
                 GROUP BY t.channel,t.status ORDER BY t.channel,t.status""",
                  (TENANT,BRANCH,start,end))
            tender=c.fetchall()
            c.execute("""SELECT kind,channel,COUNT(*)::int AS n,
                   COALESCE(SUM(signed_amount_xaf),0)::bigint AS amount
                 FROM v3r_b_finance_drafts WHERE tenant_id=%s AND branch_id=%s
                 AND effective_at >= %s AND effective_at < %s
                 GROUP BY kind,channel ORDER BY kind,channel""",
                   (TENANT,BRANCH,start,end))
            manual=c.fetchall()
            c.execute("""SELECT COUNT(*)::int AS n,
                   COALESCE(SUM(f.amount_xaf),0)::bigint AS value
                 FROM v3r_finance_events f JOIN v3r_orders o ON o.id=f.order_id
                 WHERE o.tenant_id=%s AND o.branch_id=%s
                   AND o.created_at >= %s AND o.created_at < %s
                   AND f.kind='RECEIVABLE_TEST'""",
                   (TENANT,BRANCH,start,end))
            ar=c.fetchone()
            c.execute("""SELECT COUNT(*)::int AS n,
                 COALESCE(SUM(o.amount_xaf-COALESCE(d.amount_xaf,0)),0)::bigint AS net
                 FROM v3r_orders o LEFT JOIN v24_order_discounts d ON d.order_id=o.id
                 WHERE o.tenant_id=%s AND o.branch_id=%s
                   AND o.created_at >= %s AND o.created_at < %s""",
                   (TENANT,BRANCH,start,end))
            net=c.fetchone()
    return {
      "grade":"SYNTHETIC_TEST_ONLY_NO_CANONICAL_ACCOUNTING",
      "day":day.isoformat(),"shift":shift,"start":utc(start),"endExclusive":utc(end),
      "scope":{"tenant":TENANT,"branch":BRANCH},
      "sales":{"count":sales["n"],"grossXaf":int(sales["gross"]),
               "discountXaf":int(disc["discount"]),"netDueXaf":int(net["net"])},
      "tenderEvents":tender,
      "manualFinanceDraftEvents":manual,
      "receivableEvents":{"count":ar["n"],"sourceGrossXaf":int(ar["value"])},
      "caveat":"Manual Finance drafts are separate ledger candidates, not added to gross sales. Receivable events are original gross event markers, not debt settlements. Provider-pending is not paid.",
      "officialCashBalance":None,"officialReconciliation":False,
      "realMonetaryExecution":False}
@r4.get("/stock-asof")
def stock_asof(sku:str,at:datetime,actor=Depends(auth)):
    actor_role(actor,{"MERCHANT_TEST","REVIEWER_TEST","CASHIER_TEST"})
    if at.tzinfo is None or at.utcoffset() is None:stop(422,"AWARE_ASOF_REQUIRED")
    with connect() as db:
        with db.cursor() as c:
            c.execute("SELECT sku,stock_qty,family,active FROM v3r_products WHERE sku=%s",(sku,))
            product=c.fetchone()
            if not product:stop(404,"SKU_NOT_FOUND")
            c.execute("""SELECT id::text,delta,quantity_after,created_at
                       FROM v3r_stock_movements WHERE sku=%s AND created_at<=%s
                       ORDER BY created_at DESC,id DESC LIMIT 1""",(sku,at))
            last=c.fetchone()
            c.execute("""SELECT COUNT(*)::int AS n,COALESCE(SUM(delta),0)::bigint AS signed
                       FROM v3r_stock_movements WHERE sku=%s AND created_at<=%s""",
                       (sku,at))
            history=c.fetchone()
            c.execute("""SELECT id::text,delta,quantity_after,created_at
                       FROM v3r_stock_movements WHERE sku=%s
                       ORDER BY created_at DESC,id DESC LIMIT 1""",(sku,))
            latest=c.fetchone()
    current=product["stock_qty"]
    asof=last["quantity_after"] if last else None
    # No movement means historical starting quantity is unknown and must not be inferred.
    full_consistency=None if current is None or latest is None else (
             latest["quantity_after"]==current)
    return {
      "grade":"SYNTHETIC_TEST_NATIVE_STOCK_ONLY",
      "sku":sku,"asOf":utc(at),"currentNativeQuantity":current,
      "asOfQuantityFromMovement":asof,
      "asOfAvailable":last is not None and asof is not None,
      "asOfMovementCount":history["n"],
      "asOfDeltaSum":int(history["signed"]),
      "latestNativeMovementMatchesCurrentStock":full_consistency,
      "explicitWithheldReason":None if last and asof is not None else
               "NO_SOURCE_MOVEMENT_ANCHOR_OR_UNKNOWN_QUANTITY",
      "snapshotAsOfIndependentRestoreProven":False,
      "legacyHistoricalStockParityProven":False}

# R5 consolidated operator-readable daily statement and financial event separation.
import csv,io
from fastapi.responses import PlainTextResponse
@r4.get("/daily/export")
def daily_export(day:date,shift:str=Query("ALL"),actor=Depends(auth)):
    who=actor_role(actor,{"MERCHANT_TEST","REVIEWER_TEST","CLOSER_TEST"})
    result=daily(day=day,shift=shift,actor=actor)
    output=io.StringIO()
    writer=csv.writer(output)
    writer.writerow(["WND V3 SYNTHETIC TEST — DAILY/SHIFT OPERATOR STATEMENT"])
    writer.writerow(["BUSINESS_DAY",day.isoformat(),"SHIFT",shift])
    writer.writerow(["START_UTC",result["start"],"END_EXCLUSIVE_UTC",result["endExclusive"]])
    writer.writerow(["SECTION","CHANNEL_OR_KIND","STATUS","COUNT","AMOUNT_XAF"])
    sale=result["sales"]
    writer.writerow(["SALES","GROSS_TEST","NOT_SETTLEMENT",sale["count"],sale["grossXaf"]])
    writer.writerow(["ADJUSTMENT","DISCOUNT_TEST","MARKETING_OR_STAFF_OFFSET","","-"+str(sale["discountXaf"])])
    writer.writerow(["SALES","NET_DUE_TEST","NOT_CASH_BALANCE","",sale["netDueXaf"]])
    for e in result["tenderEvents"]:
        writer.writerow(["TEST_TENDER_INTENT",e["channel"],e["status"],e["n"],e["amount"]])
    for e in result["manualFinanceDraftEvents"]:
        writer.writerow(["MANUAL_FINANCE_DRAFT",e["kind"],e["channel"],e["n"],e["amount"]])
    ar=result["receivableEvents"]
    writer.writerow(["AR_SOURCE_MARKER","RECEIVABLE_TEST","ORIGINAL_GROSS_NOT_NEW_SALES",
                      ar["count"],ar["sourceGrossXaf"]])
    writer.writerow(["DISCLAIMER","NOT_OFFICIAL_LEDGER","NO_REAL_PSP_NO_PC5","",""])
    return PlainTextResponse(output.getvalue(),media_type="text/csv",
       headers={"Content-Disposition":'attachment; filename="WND-V3-TEST-daily-shift.csv"',
                "X-TEST-STATEMENT":"NOT_OFFICIAL_FINANCE",
                "Cache-Control":"no-store"})
