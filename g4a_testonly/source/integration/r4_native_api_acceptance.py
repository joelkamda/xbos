"""R4 real PG17 daily/shift report and as-of stock readback acceptance."""
import uuid,json,urllib.request,urllib.error,urllib.parse
from rehearsal_v3.seed import connect
N=0
BASE="http://127.0.0.1:8791"
def ok(val,key):
 global N
 if not val:raise AssertionError("R4_"+key)
 N+=1
def call(path,token=None,status=200):
 request=urllib.request.Request(BASE+path,headers={"X-Rehearsal-Token":token} if token else {})
 try:
  with urllib.request.urlopen(request,timeout=10) as response:
   got=response.status;data=response.read()
 except urllib.error.HTTPError as ex:
  got=ex.code;data=ex.read()
 if got!=status:raise AssertionError("R4_HTTP_%s_EXPECT_%s_%s"%(got,status,path))
 return got if got>=400 else json.loads(data)
def login(user):
 req=urllib.request.Request(BASE+"/api/v3/session",method="POST",
     headers={"Content-Type":"application/json"},
     data=json.dumps({"username":user,"password":"V24-ONLY-"+user+"-synthetic"}).encode())
 with urllib.request.urlopen(req,timeout=10) as response:return json.load(response)["token"]
def main():
 tokens={r:login(r) for r in ("merchant","reviewer","cashier")}
 ok(call("/api/v3/health")["database"]=="v24_native_d7_test","NATIVE_DB_ONLY")
 with connect() as db:
  with db.cursor() as c:
   dates=["2026-11-22T07:59:59+01:00","2026-11-22T08:00:00+01:00",
          "2026-11-22T17:59:59+01:00","2026-11-22T18:00:00+01:00",
          "2026-11-23T07:59:59+01:00"]
   ids=[]
   for i,date in enumerate(dates):
    oid=uuid.uuid4();ids.append(oid)
    c.execute("""INSERT INTO v3r_orders(id,idempotency_key,created_at,tenant_id,branch_id,zone,status,amount_xaf)
          VALUES(%s,%s,%s,920002,1,'MAIN','UNPAID_TEST',1200)""",
          (oid,"r4-native-day-"+str(i),date))
    c.execute("""INSERT INTO v3r_finance_events(id,order_id,kind,amount_xaf)
       VALUES(%s,%s,'RECEIVABLE_TEST',1200)""",(uuid.uuid4(),oid))
   c.execute("""INSERT INTO v24_order_discounts
       (order_id,tenant_id,branch_id,amount_xaf,reason,created_by)
       VALUES(%s,920002,1,200,'Synthetic R4 promotion','merchant')""",(ids[1],))
   c.execute("""INSERT INTO v24_tender_intents(id,order_id,tenant_id,branch_id,
       idem,channel,amount_xaf,status,created_by,created_at)
       VALUES(%s,%s,920002,1,'r4-cash-test-1','CASH',700,'CASH_RECEIVED_TEST','cashier',
       '2026-11-22T10:00:00+01:00')""",(uuid.uuid4(),ids[1]))
   c.execute("""INSERT INTO v24_tender_intents(id,order_id,tenant_id,branch_id,
       idem,channel,amount_xaf,status,created_by,created_at)
       VALUES(%s,%s,920002,1,'r4-provider-pending-1','MTN',300,'PROVIDER_PENDING_TEST','cashier',
       '2026-11-22T10:01:00+01:00')""",(uuid.uuid4(),ids[1]))
   for idx,(kind,amount,channel) in enumerate([
       ("INCOME_TEST",300,"CASH"),("EXPENSE_TEST",-100,"CASH")]):
    c.execute("""INSERT INTO v3r_b_finance_drafts(id,tenant_id,branch_id,idempotency_key,
       kind,channel,signed_amount_xaf,effective_at,note,created_by)
       VALUES(%s,920002,1,%s,%s,%s,%s,'2026-11-22T09:00:00+01:00',
       'Synthetic independent manual Finance draft','merchant')""",
       (uuid.uuid4(),"r4-finance-"+str(idx),kind,channel,amount))
   # Inject two attributable native stock movements in a single TEST transaction.
   # Current product quantity matches the latest TEST movement after closure.
   c.execute("UPDATE v3r_products SET stock_qty=43 WHERE sku='TEST-DRINK-01'")
   for date,delta,after in [("2026-11-21T13:00:00+01:00",-1,44),
       ("2026-11-22T12:00:00+01:00",-1,43)]:
    c.execute("""INSERT INTO v3r_stock_movements(id,sku,delta,quantity_after,created_at)
       VALUES(%s,'TEST-DRINK-01',%s,%s,%s)""",
       (uuid.uuid4(),delta,after,date))
  db.commit()
 ok(True,"FIXTURE_CREATED_NATIVE_PG17")
 def daily(day,shift,token=tokens["reviewer"],status=200):
  return call("/api/v3/v24/r4/daily?day="+day+"&shift="+shift,token,status)
 all_day=daily("2026-11-22","ALL")
 ok(all_day["sales"]["count"]==4 and all_day["sales"]["grossXaf"]==4800,
    "BUSINESS_DAY_NOT_CIVIL_DAY")
 ok(all_day["sales"]["discountXaf"]==200 and all_day["sales"]["netDueXaf"]==4600,
    "SALES_DISCOUNT_SINGLE_OFFSET")
 ok(all_day["receivableEvents"]["count"]==4 and all_day["receivableEvents"]["sourceGrossXaf"]==4800,
    "AR_SOURCE_MARKERS_NOT_NEW_SALES")
 ok(any(t["channel"]=="CASH" and t["amount"]==700 for t in all_day["tenderEvents"]),
    "REAL_NATIVE_CASH_TENDER")
 ok(any(t["channel"]=="MTN" and t["status"]=="PROVIDER_PENDING_TEST"
    and t["amount"]==300 for t in all_day["tenderEvents"]),"PENDING_MTN_NOT_PAID")
 ok(len(all_day["manualFinanceDraftEvents"])==2 and all_day["officialCashBalance"] is None,
    "MANUAL_FINANCE_SEPARATE_FROM_SALES")
 ok(all_day["officialReconciliation"] is False and all_day["realMonetaryExecution"] is False,
    "NO_FALSE_FINANCIAL_FINALITY")
 day=daily("2026-11-22","DAY")
 night=daily("2026-11-22","NIGHT")
 prev=daily("2026-11-21","NIGHT")
 ok(day["sales"]["count"]==2 and day["sales"]["grossXaf"]==2400,"DAY_0800_TO_1800")
 ok(night["sales"]["count"]==2 and night["sales"]["grossXaf"]==2400,"NIGHT_1800_TO_NEXT_0800")
 ok(prev["sales"]["count"]==1,"PREVIOUS_BUSINESS_DAY_0759")
 ok(day["endExclusive"]==night["start"],"SHIFTS_JOIN_WITHOUT_GAP")
 ok(night["endExclusive"].startswith("2026-11-23T07:00:00"),"NIGHT_ENDS_NEXT_0800_LOCAL")
 ok(daily("2026-11-22","BAD",status=422)==422,"INVALID_SHIFT_DENIED")
 ok(daily("2026-11-22","ALL",token=tokens["cashier"],status=403)==403,
    "CASHIER_FINANCE_AGGREGATE_DENIED")
 def stock(sku,t):
  return call("/api/v3/v24/r4/stock-asof?sku="+urllib.parse.quote(sku,safe="")+
    "&at="+urllib.parse.quote(t,safe=""),tokens["reviewer"])
 first=stock("TEST-DRINK-01","2026-11-22T11:59:59+01:00")
 after=stock("TEST-DRINK-01","2026-11-22T12:00:00+01:00")
 ok(first["asOfQuantityFromMovement"]==44,"ASOF_BEFORE_MOVEMENT")
 ok(after["asOfQuantityFromMovement"]==43 and
    after["latestNativeMovementMatchesCurrentStock"] is True,
    "ASOF_AFTER_MOVEMENT_MATCHES_CURRENT")
 ok(after["asOfMovementCount"]==2 and after["asOfDeltaSum"]==-2,
    "MOVEMENT_SUM_SOURCE_READBACK")
 no_history=stock("TEST-FOOD-01","2026-11-22T23:00:00+01:00")
 ok(no_history["asOfAvailable"] is False and
    no_history["asOfQuantityFromMovement"] is None and
    no_history["explicitWithheldReason"],"UNKNOWN_HISTORICAL_ANCHOR_WITHHELD")
 ok(call("/api/v3/v24/r4/stock-asof?sku=TEST-DRINK-01&at=2026-11-22T10%3A00%3A00",
         tokens["reviewer"],422)==422,"NAIVE_STOCK_ASOF_DENIED")
 ok(call("/api/v3/v24/r4/stock-asof?sku=NOT-EXIST&at=2026-11-22T23%3A00%3A00%2B01%3A00",
         tokens["reviewer"],404)==404,"UNKNOWN_SKU_DENIED")
 print("R4_NATIVE_FINANCE_INVENTORY_PG_PASS="+str(N))
 print("R4_OFFICIAL_FINANCE_POSTED=False")
 print("R4_HISTORICAL_WND_REWRITTEN=False")
if __name__=="__main__":main()
