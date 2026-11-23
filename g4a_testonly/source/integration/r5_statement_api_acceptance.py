"""R5 integrated TEST Finance statement, download, shift reconciliation and
native event audit. Run after R4 fixture tests in same fresh no-egress PG17.
"""
import urllib.request,urllib.error,json,csv,io
BASE="http://127.0.0.1:8791";TOTAL=0
def check(x,k):
 global TOTAL
 if not x:raise AssertionError("R5_STATEMENT_"+k)
 TOTAL+=1
def call(path,token,method="GET",payload=None,expected=200,raw=False):
 h={"X-Rehearsal-Token":token,"Content-Type":"application/json"}
 req=urllib.request.Request(BASE+path,method=method,headers=h,
      data=json.dumps(payload).encode() if payload is not None else None)
 try:
  with urllib.request.urlopen(req,timeout=15) as r:
   status=r.status;body=r.read();headers=dict(r.headers)
 except urllib.error.HTTPError as e:
  status=e.code;body=e.read();headers=dict(e.headers)
 if status!=expected:raise AssertionError("R5_HTTP_%s_NOT_%s_%s"%(status,expected,path))
 return status if status>=400 else ((body,headers) if raw else json.loads(body))
def login(actor):
 req=urllib.request.Request(BASE+"/api/v3/session",method="POST",
       headers={"Content-Type":"application/json"},
       data=json.dumps({"username":actor,"password":"V24-ONLY-"+actor+"-synthetic"}).encode())
 with urllib.request.urlopen(req,timeout=10) as f:return json.load(f)["token"]
def main():
 m=login("merchant");rev=login("reviewer");cash=login("cashier")
 day=call("/api/v3/v24/r4/daily?day=2026-11-22&shift=DAY",rev)
 check(day["sales"]["grossXaf"]==2400 and day["sales"]["discountXaf"]==200,"NATIVE_DAILY_FIGURES")
 response,headers=call("/api/v3/v24/r4/daily/export?day=2026-11-22&shift=DAY",rev,raw=True)
 csv_rows=list(csv.reader(io.StringIO(response.decode())))
 check(any(row[:2]==["SALES","GROSS_TEST"] and row[-1]=="2400" for row in csv_rows),"DAILY_CSV_GROSS_2400")
 check(any(row[:2]==["ADJUSTMENT","DISCOUNT_TEST"] and row[-1]=="-200" for row in csv_rows),"DAILY_CSV_DISCOUNT_NEGATIVE")
 check(any("PROVIDER_PENDING_TEST" in row for row in csv_rows),"PENDING_CHANNEL_MARKED_NOT_SETTLED")
 check(any("MANUAL_FINANCE_DRAFT" in row for row in csv_rows),"MANUAL_FINANCE_SEPARATE")
 check(any("NOT_OFFICIAL_LEDGER" in row for row in csv_rows),"TEST_ONLY_WATERMARK")
 check(dict((k.lower(),v) for k,v in headers.items())["x-test-statement"]=="NOT_OFFICIAL_FINANCE",
       "NO_OFFICIAL_FINANCE_HEADER")
 check(call("/api/v3/v24/r4/daily/export?day=2026-11-22&shift=DAY",
       cash,expected=403)==403,"CASHIER_PRIVATE_FINANCE_EXPORT_DENIED")
 statement=call("/api/v3/finance-b/entries?as_of=2026-11-23T20%3A00%3A00%2B01%3A00&limit=50",rev)
 check(len(statement["rows"])>=2,"NATIVE_FINANCE_TEST_ENTRIES_READBACK")
 request_body={"tenant_id":920002,"branch_id":1,"business_date":"2026-11-22",
               "shift":"DAY","cashier_count_xaf":700}
 result=call("/api/v3/finance-b/reconciliation/draft",m,method="POST",payload=request_body)
 check(result["draftSaved"] and result["status"]=="RECON_DRAFT_TEST_NOT_CLOSED",
       "RECON_DRAFT_NATIVE_PG17")
 check(call("/api/v3/finance-b/reconciliation/draft",m,method="POST",
        payload=request_body,expected=409)==409,"DUPLICATE_RECON_DENIED")
 print("R5_STATEMENT_RECON_PG17_PASS="+str(TOTAL))
 print("R5_OFFICIAL_SETTLEMENT=False")
if __name__=="__main__":main()
