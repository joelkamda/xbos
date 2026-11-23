"""R7 one-source N+PK+PA+W native PostgreSQL17 TEST acceptance.
All synthetic 920002/1, no genuine PC5, Finance posting, printer or PSP.
"""
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import json,urllib.request,urllib.error
from rehearsal_v3.seed import connect
BASE="http://127.0.0.1:8791";COUNT=0
def ck(value,why):
 global COUNT
 if not value:raise AssertionError("R7_"+why)
 COUNT+=1
def req(path,token=None,method="GET",body=None,expect=None):
 headers={"Content-Type":"application/json"}
 if token:headers["X-Rehearsal-Token"]=token
 r=urllib.request.Request(BASE+path,method=method,headers=headers,
   data=json.dumps(body).encode() if body is not None else None)
 try:
  with urllib.request.urlopen(r,timeout=25) as f:status=f.status;data=f.read()
 except urllib.error.HTTPError as e:status=e.code;data=e.read()
 if expect is not None:
  if status!=expect:raise AssertionError(f"HTTP {status} expected {expect} in {path}: {data[:180]!r}")
  if status>=400:return status
 elif status>=400:
  raise AssertionError(f"HTTP {status} in {path}: {data[:180]!r}")
 return json.loads(data)
def login(who):
 x=req("/api/v3/session",method="POST",body={
  "username":who,"password":"V24-ONLY-"+who+"-synthetic"})
 ck(x["pc5"] is False and x.get("token"),"SIGNED_SYNTHETIC_ROLE_"+who)
 return x["token"]
def merchant_product(merchant):
 r=req("/api/v3/v24/products/draft",merchant,"POST",{"name":"Synthetic R7 test soda"})
 sku=r["sku"]
 ck(r["revision"]==1,"MERCHANT_DRAFT")
 x=req("/api/v3/v24/products/"+sku,merchant,"PUT",{
   "revision":1,"name":"Synthetic R7 test soda","category":"MOCK DRINK",
   "family":"bar","unit":"BOTTLE","main_xaf":1700,
   "vip_xaf":2300,"bar_xaf":1900,"stock_qty":20})
 ck(x["revision"]==2 and x["priceRevisions"]==[2,2,2],"NATIVE_ZONE_PRICE_VERSIONS")
 y=req("/api/v3/v24/products/"+sku+"/review",merchant,"POST",{"revision":2})
 ck(y["revision"]==3 and y["priceRevisions"]==[2,2,2],"REVIEW_NATIVE_VERSIONS")
 return sku,y["priceRevisions"]
def main():
 m=login("merchant");review=login("reviewer");cash=login("cashier")
 sku,revs=merchant_product(m)
 path="/api/v3/v24/products/"+sku+"/publish"
 ck(req(path,review,"POST",{"revision":3},expect=409)==409,"PK_PRICE_VERSIONS_REQUIRED")
 ck(req(path,cash,"POST",{"revision":3,"price_revisions":revs},expect=403)==403,
    "CASHIER_CANNOT_PUBLISH")
 ck(req(path,review,"POST",{"revision":3,"price_revisions":[1,1,1]},expect=409)==409,
    "STALE_ZONE_PRICE_VERSIONS_DENIED")
 published=req(path,review,"POST",{"revision":3,"price_revisions":revs})
 ck(published.get("nativeCatalog") and published["r7NativePkPreflight"]["packSigningVerified"] is False
   if "packSigningVerified" in published["r7NativePkPreflight"] else (
      published.get("nativeCatalog") and published["r7NativePkPreflight"]["actualPc5"] is False),
    "COMBINED_N_PK_PA_NATIVE_PUBLISH")
 ck(published["sourceGrade"]=="SYNTHETIC_PG17_PERMISSION_NOT_GENUINE_PC5"
    and published["genuinePc5"] is False,"PA_GRANT_NOT_GENUINE_PC5")
 ck(req(path,review,"POST",{"revision":3,"price_revisions":revs},expect=409)==409,
    "REVISION_REPLAY_DENIED")
 catalog=req("/api/v3/catalog?zone=VIP",cash)
 ck(any(x["sku"]==sku and x["amount_xaf"]==2300 for x in catalog["items"]),
    "NATIVE_VIP_PRICE_REAL_PG")
 with connect() as db:
  with db.cursor() as c:
   c.execute("SELECT COUNT(*) AS n FROM v24_product_audit WHERE sku=%s AND action='PUBLISH'",(sku,))
   audit=c.fetchone()["n"]
  db.commit()
 ck(audit==1,"ONE_PUBLICATION_AUDIT")

 # TEST PA denial: revoke scoped grant, forbid publisher; then restore fixture.
 sku2,revs2=merchant_product(m)
 p2="/api/v3/v24/products/"+sku2+"/publish"
 with connect() as db:
  with db.cursor() as c:c.execute("""UPDATE v24_pa_test_publish_grants
       SET revoked_at=NOW() WHERE actor_ref='reviewer'""")
  db.commit()
 ck(req(p2,review,"POST",{"revision":3,"price_revisions":revs2},expect=403)==403,
    "PA_TEST_GRANT_REVOKED_DENIES")
 with connect() as db:
  with db.cursor() as c:c.execute("""UPDATE v24_pa_test_publish_grants
       SET revoked_at=NULL WHERE actor_ref='reviewer'""")
  db.commit()
 # TEST PK denial: revoke synthetic pack in DB: no publication, then restore.
 with connect() as db:
  with db.cursor() as c:c.execute("""UPDATE v24_pk_test_pack_readback
       SET state='REVOKED_SOURCE' WHERE tenant_id=920002 AND branch_id=1""")
  db.commit()
 ck(req(p2,review,"POST",{"revision":3,"price_revisions":revs2},expect=409)==409,
    "PK_PACK_REVOKED_DENIED")
 with connect() as db:
  with db.cursor() as c:c.execute("""UPDATE v24_pk_test_pack_readback
       SET state='ACTIVE_SOURCE' WHERE tenant_id=920002 AND branch_id=1""")
  db.commit()
 # Serialize concurrent same-SKU publication; the accepted N-CAS owner tested this
 # in isolation. Reconfirm against PK+PA combined hooks.
 def publish_second():
  try:return req(p2,review,"POST",{"revision":3,"price_revisions":revs2})["nativeCatalog"]
  except AssertionError:return "CONFLICT"
 with ThreadPoolExecutor(max_workers=2) as pool:
  results=list(pool.map(lambda _:publish_second(),[1,2]))
 ck(results.count(True)==1 and results.count("CONFLICT")==1,
    "COMBINED_CONCURRENT_PUBLISH_SINGLE_WINNER")
 with connect() as db:
  with db.cursor() as c:
   c.execute("SELECT COUNT(*) AS n FROM v24_product_audit WHERE sku=%s AND action='PUBLISH'",(sku2,))
   a=c.fetchone()["n"]
   c.execute("SELECT COUNT(*) AS n FROM v3r_prices WHERE sku=%s",(sku2,))
   prices=c.fetchone()["n"]
  db.commit()
 ck(a==1 and prices==3,"CONCURRENT_ONE_AUDIT_AND_THREE_PRICES")
 # W native, same app and same TEST PostgreSQL: request/review/preview and replay.
 order=req("/api/v3/orders",cash,"POST",{"idempotency_key":"r7-unified-w-"+uuid4().hex,
      "zone":"MAIN","lines":[{"sku":sku,"quantity":1}]})
 oid=order["orderId"]
 ck(order["totalXaf"]==1700,"SOURCE_REAL_NATIVE_ORDER")
 route="/api/v3/v24/w/receipt-custody"
 w=req(route+"/orders/"+oid+"/request",cash,"POST",
       {"idem":"r7-native-reprint-0001","reason":"Synthetic duplicate preview"})
 ref=w["requestId"]
 ck(w["status"]=="PENDING_REVIEW_TEST" and w["officialReceiptReprinted"] is False,
    "W_RECEIPT_REQUEST_NATIVE_PG")
 ck(req(route+"/orders/"+oid+"/request",cash,"POST",
       {"idem":"r7-native-reprint-0001","reason":"Synthetic duplicate preview"},expect=409)==409,
    "W_REPRINT_IDEMPOTENCY")
 ck(req(route+"/requests/"+ref+"/preview",cash,expect=409)==409,
    "W_UNAPPROVED_PREVIEW_DENIED")
 ck(req(route+"/requests/"+ref+"/review",cash,"POST",{
     "revision":1,"decision":"APPROVE_PREVIEW_TEST","reason":"Independent TEST review"},expect=403)==403,
    "W_CASHIER_NOT_REVIEWER")
 approved=req(route+"/requests/"+ref+"/review",review,"POST",{
    "revision":1,"decision":"APPROVE_PREVIEW_TEST","reason":"Independent TEST review"})
 ck(approved["revision"]==2 and approved["noPhysicalPrinterEffect"] is True,
    "W_INDEPENDENT_REVIEW_PERSISTED")
 ck(req(route+"/requests/"+ref+"/review",review,"POST",{
    "revision":1,"decision":"APPROVE_PREVIEW_TEST","reason":"Independent TEST review"},expect=409)==409,
    "W_STALE_APPROVAL_DENIED")
 preview=req(route+"/requests/"+ref+"/preview",cash)
 ck(preview["printed"] is False and preview["printCount"]==0 and preview["state"]==
    "APPROVED_DUPLICATE_PREVIEW_TEST_ONLY","W_SAFE_NO_PRINTER_PREVIEW")
 ck(req(route+"/requests/"+ref+"/preview",review,expect=403)==403,
    "W_REVIEWER_CANNOT_VIEW_DUPLICATE")
 # Any changed underlying tender invalidates cached custody snapshot.
 req("/api/v3/v24/orders/"+oid+"/tender",cash,"POST",{
    "idem":"r7-later-tender-0001","channel":"CASH","amount_xaf":100,
    "state":"CASH_RECEIVED_TEST"})
 ck(req(route+"/requests/"+ref+"/preview",cash,expect=409)==409,
    "W_MUTATED_SOURCE_DENIED_AFTER_APPROVAL")
 print("R7_UNIFIED_N_PK_PA_W_PG17_PASS="+str(COUNT))
 print("R7_REAL_PC5=False")
 print("R7_REAL_PAYMENT=False")
 print("R7_PHYSICAL_PRINTER=False")
if __name__=="__main__":main()
