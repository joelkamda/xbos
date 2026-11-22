"""Integrated W native shift and N first-write scope acceptance, synthetic PG17 only."""
import json,urllib.request,urllib.error,urllib.parse
BASE="http://127.0.0.1:8791";K=0
def check(x,msg):
 global K
 if not x:raise AssertionError("R6_W_N_"+msg)
 K+=1
def req(path,token,method="GET",body=None,expected=200):
 data=json.dumps(body).encode() if body is not None else None
 r=urllib.request.Request(BASE+path,method=method,data=data,
     headers={"X-Rehearsal-Token":token,"Content-Type":"application/json"})
 try:
  with urllib.request.urlopen(r,timeout=20) as f:status=f.status;raw=f.read()
 except urllib.error.HTTPError as e:status=e.code;raw=e.read()
 if status!=expected:raise AssertionError("STATUS_"+str(status)+"_"+str(expected)+"_"+raw[:170].decode("utf-8","replace"))
 return status if status>=400 else json.loads(raw)
def login(role):
 request=urllib.request.Request(BASE+"/api/v3/session",method="POST",
    headers={"Content-Type":"application/json"},
    data=json.dumps({"username":role,"password":"V24-ONLY-"+role+"-synthetic"}).encode())
 with urllib.request.urlopen(request) as f:return json.load(f)["token"]
def main():
 m=login("merchant");r=login("reviewer");c=login("cashier")
 url="/api/v3/v24/w/shift-handoff/preview"
 live=req("/api/v3/v24/r4/daily?day=2026-11-22&shift=DAY",r)
 native_cash=sum(int(x["amount"]) for x in live["tenderEvents"]
       if x["channel"]=="CASH" and x["status"]=="CASH_RECEIVED_TEST")
 native_pending=sum(int(x["amount"]) for x in live["tenderEvents"]
       if x["status"]=="PROVIDER_PENDING_TEST")
 expected_cash=100+native_cash
 body={"business_day":"2026-11-22","shift":"DAY","opening_cash_xaf":100,
       "physically_counted_cash_xaf":expected_cash+50,
       "discrepancy_note":"Synthetic count derived from native daily"}
 a=req(url,r,method="POST",body=body)
 check(a["cashReceivedTenderTestXaf"]==native_cash and a["expectedCashTestXaf"]==expected_cash,
       "SYNTHETIC_NATIVE_EXPECTED_CASH")
 check(a["physicalCashCountXaf"]==expected_cash+50 and a["varianceSignedXaf"]==50 and
      a["varianceClassification"]=="SURPLUS","SIGNED_CASH_VARIANCE_SURPLUS")
 check(a["providerPendingIntentXaf"]==native_pending and a["manualCashDraftSignedXafNotCounted"]==200,
      "NO_PENDING_OR_MANUAL_DOUBLE_COUNT")
 check(a["officialReconciliationClosed"] is False and a["financePosted"] is False,
      "HUMAN_COUNT_NEVER_OFFICIAL_POST")
 negative=dict(body,physically_counted_cash_xaf=expected_cash-150)
 b=req(url,m,method="POST",body=negative)
 check(b["varianceSignedXaf"]==-150 and b["varianceClassification"]=="SHORTAGE",
       "REAL_NATIVE_SIGNED_SHORTAGE")
 check(req(url,c,method="POST",body=body,expected=403)==403,
       "CASHIER_CANNOT_VIEW_UNSCOPED_FINANCE_AGGREGATE")
 bad=dict(body,shift="NIGHT")
 d=req(url,r,method="POST",body=bad)
 check(d["cashReceivedTenderTestXaf"]==0 and d["providerPendingIntentXaf"]==0,
       "DAY_NIGHT_SEPARATION_NATIVE")
 check(req(url,r,method="POST",body={**body,"piece_counts":{"100":1}},
       expected=422)==422,"DENOMINATION_MISMATCH_DENIED")
 check(req(url,r,method="POST",body={**body,
       "physically_counted_cash_xaf":expected_cash,
       "piece_counts":{"100":expected_cash//100}})["cashDenominationCountVerified"] is True,
       "DENOMINATIONS_VERIFIED")
 fence=req("/api/v3/v24/recovery/first-write-fence",r)
 check(fence.get("safeToRestoreWithoutReview") is not True,"NO_BLIND_RESTORE_FENCE")
 check(req("/api/v3/v24/recovery/first-write-fence",c,expected=403)==403,
       "CASHIER_NO_RECOVERY_AUTH")
 print("R6_NATIVE_W_N_REALPG17_PASS="+str(K))
if __name__=="__main__":main()
