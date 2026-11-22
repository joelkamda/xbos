"""Verify negative stock count differences never become POS COGS.
Runs on the accepted R6 synthetic PostgreSQL17; no real Finance writes.
"""
import json,urllib.error,urllib.request
P="http://127.0.0.1:8791"
def hit(path,method="GET",body=None,token=None,expected=200):
 req=urllib.request.Request(P+path,method=method,
   data=json.dumps(body).encode() if body is not None else None,
   headers={"Content-Type":"application/json",
      **({"X-Rehearsal-Token":token} if token else {})})
 try:
  with urllib.request.urlopen(req,timeout=15) as f:
   status=f.status;data=f.read()
 except urllib.error.HTTPError as e:
  status=e.code;data=e.read()
 assert status==expected,(path,status,expected,data[:80])
 return status if status>=400 else json.loads(data)
def main():
 merchant=hit("/api/v3/session","POST",{"username":"merchant","password":"V24-ONLY-merchant-synthetic"})["token"]
 reviewer=hit("/api/v3/session","POST",{"username":"reviewer","password":"V24-ONLY-reviewer-synthetic"})["token"]
 cashier=hit("/api/v3/session","POST",{"username":"cashier","password":"V24-ONLY-cashier-synthetic"})["token"]
 a=hit("/api/v3/v24/stock/TEST-DRINK-01/cost-policy","POST",
        {"policy":"DRINK_AUTO_TEST","unit_cost_xaf":650},merchant)
 assert a["officialFinancePosted"] is False
 b=hit("/api/v3/v24/stock/TEST-DRINK-01/cogs",token=reviewer)
 # R4 fixture introduced two unlinked (count) corrections of -1 each.
 # SOF R6 source order introduced exactly two sale units.
 assert b["depletedNativeUnits"]==2,(b,"COUNT_ADJUSTMENT_MUST_NOT_INFLATE_COGS")
 assert b["computedTestCogsXaf"]==1300 and b["officialJournalPosted"] is False,b
 assert hit("/api/v3/v24/stock/TEST-DRINK-01/cogs",token=cashier,expected=403)==403
 print("R6_COGS_SALE_VS_STOCK_COUNT_REAL_PG_PASS=4")
if __name__=="__main__":main()
