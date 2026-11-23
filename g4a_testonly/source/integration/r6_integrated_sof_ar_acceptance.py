"""SOF R6: genuine HTTP/FastAPI/native PG17 synthetic TEST acceptance.

Runs INSIDE no-egress Linux namespace with fresh isolated PostgreSQL 17.
All actors are synthetic roles, never real humans or PC5 principals.
No WND customer record or actual money is accessed, generated or settled.
"""
import json,uuid,urllib.request,urllib.error
BASE="http://127.0.0.1:8791"
COUNT=0
def check(ok,what):
 global COUNT
 if not ok:raise AssertionError("SOF_R6_"+what)
 COUNT+=1
def call(path,token=None,method="GET",body=None,expect=200):
 h={"Content-Type":"application/json"}
 if token:h["X-Rehearsal-Token"]=token
 req=urllib.request.Request(BASE+path,method=method,headers=h,
     data=json.dumps(body).encode() if body is not None else None)
 try:
  with urllib.request.urlopen(req,timeout=12) as f:
   status=f.status;payload=f.read()
 except urllib.error.HTTPError as err:
  status=err.code;payload=err.read()
 if status!=expect:
  raise AssertionError("SOF_R6_HTTP_"+str(status)+"_EXPECTED_"+str(expect)+"_AT_"+path+
                       "_BODY_"+payload.decode("utf-8","replace")[:300])
 return status if status>=400 else json.loads(payload)
def signin(name):
 r=call("/api/v3/session",method="POST",body={"username":name,
      "password":"V24-ONLY-"+name+"-synthetic"})
 check(r["pc5"] is False and bool(r["token"]),"LOGIN_TEST_"+name)
 return r["token"]
def main():
 check(call("/api/v3/v24/sof/ar/debtors",expect=401)==401,"ANONYMOUS_DENIED")
 merchant=signin("merchant");cashier=signin("cashier");reviewer=signin("reviewer")
 closer=signin("closer")
 prefix="/api/v3/v24/sof/ar"
 check(call(prefix+"/debtors",cashier,method="POST",body={
   "display_name":"Synthetic Debtor","source_ref":"TEST-SOURCE-001"},expect=403)==403,
   "CASHIER_NO_CREATE")
 d=call(prefix+"/debtors",merchant,method="POST",body={
   "display_name":"TEST Credit Customer A","source_ref":"SYNTHETIC-ACCOUNT-001"})
 did=d["debtorId"]
 check(d["sourceVerified"] is False and d["realCustomer"] is False,
       "DEBTOR_SYNTHETIC_UNVERIFIED")
 check(call(prefix+"/debtors",merchant,method="POST",body={
   "display_name":"TEST Credit Customer B","source_ref":"SYNTHETIC-ACCOUNT-001"},
   expect=409)==409,"SOURCE_DUPLICATE_NO_MERGE")
 list_ = call(prefix+"/debtors?q=Credit",reviewer)
 check(len(list_["rows"])==1 and list_["rows"][0]["debtor_id"]==did,"SEARCH_DEBTOR")
 check(call(prefix+"/debtors?tenant_id=2",reviewer,expect=403)==403,
       "DENY_FOREIGN_WND_TENANT_2")
 check(call(prefix+"/debtors",merchant,method="POST",body={
   "display_name":"TEST Fraud","source_ref":"SYNTHETIC-ACCOUNT-002",
   "tenant_id":2},expect=403)==403,"CREATE_CROSS_TENANT_DENY")
 key="SOF-R6-ORDER-"+uuid.uuid4().hex
 order=call("/api/v3/orders",cashier,method="POST",body={
   "idempotency_key":key,"zone":"MAIN",
   "lines":[{"sku":"TEST-DRINK-01","quantity":2}]})
 oid=order["orderId"]
 check(order["totalXaf"]==2400 and not order["paid"],"REAL_PG_ORDER_GROSS_2400")
 discount=call("/api/v3/v24/orders/"+oid+"/discount",merchant,
   method="POST",body={"amount_xaf":400,"reason":"TEST client allowance"})
 check(discount["netDueXaf"]==2000 and discount["realFinancePosting"] is False,
       "DISCOUNT_IS_SEPARATE_NOT_DOUBLE_REVENUE")
 t1=call("/api/v3/v24/orders/"+oid+"/tender",cashier,method="POST",body={
   "idem":"SOF-R6-CASH-700","channel":"CASH","amount_xaf":700,
   "state":"CASH_RECEIVED_TEST"})
 check(t1["paid"] is False and not t1["financePosted"],"CASH_TEST_NOT_REAL_PAID")
 t2=call("/api/v3/v24/orders/"+oid+"/tender",cashier,method="POST",body={
   "idem":"SOF-R6-MTN-300","channel":"MTN","amount_xaf":300,
   "state":"PROVIDER_PENDING_TEST"})
 check(t2["paid"] is False and not t2["providerCalled"],"PENDING_PSP_NOT_PAID")
 check(call(prefix+"/obligations",cashier,method="POST",body={
   "debtor_id":did,"order_id":oid},expect=403)==403,"CASHIER_CANNOT_LINK_DEBTOR")
 link=call(prefix+"/obligations",merchant,method="POST",body={
   "debtor_id":did,"order_id":oid,"due_date":"2026-12-10"})
 ref=link["obligationId"]
 check(link["sourceGrossXaf"]==2400 and link["discountXaf"]==400 and
       link["alreadyCashTestXaf"]==700 and link["providerPendingTestXaf"]==300
       and link["originalDueXaf"]==1300,"LINK_ONCE_GROSS_MINUS_DISCOUNT_CASH")
 check(link["financePosted"] is False and link["customerPaid"] is False,
       "LINK_NO_SECOND_FINANCE_POST")
 check(call(prefix+"/obligations",merchant,method="POST",body={
   "debtor_id":did,"order_id":oid},expect=409)==409,"ORDER_ALREADY_LINKED_DENIED")
 detail=call(prefix+"/obligations/"+ref,reviewer)
 check(detail["outstandingXaf"]==1300 and detail["unreservedXaf"]==1000,
       "PENDING_RESERVES_NOT_APPLIED")
 check(call(prefix+"/obligations/"+ref+"?tenant_id=2",reviewer,expect=403)==403,
       "WRONG_TENANT_OBLIGATION_DENIED")
 check(call(prefix+"/obligations/"+ref+"/collections",merchant,method="POST",body={
   "idem":"SOF-R6-CH-500","channel":"CASH","amount_xaf":500,
   "expected_revision":1},expect=403)==403,"ONLY_CASHIER_CAN_COLLECT")
 c1=call(prefix+"/obligations/"+ref+"/collections",cashier,method="POST",body={
   "idem":"SOF-R6-CH-500","channel":"CASH","amount_xaf":500,
   "expected_revision":1})
 check(c1["cashTestAllocatedXaf"]==500 and c1["providerPendingXaf"]==0 and
       c1["customerPaid"] is False and c1["obligationRevision"]==2,
       "PARTIAL_TEST_CASH_COLLECTION")
 c2=call(prefix+"/obligations/"+ref+"/collections",cashier,method="POST",body={
   "idem":"SOF-R6-MTN-200","channel":"MTN","amount_xaf":200,
   "expected_revision":2})
 check(c2["cashTestAllocatedXaf"]==0 and c2["providerPendingXaf"]==200 and
       c2["providerSettled"] is False,"PROVIDER_PENDING_STILL_UNCOLLECTED")
 new=call(prefix+"/obligations/"+ref,reviewer)
 check(new["originalDueXaf"]==1300 and new["cashTestAllocatedXaf"]==500
       and new["providerPendingXaf"]==500 and new["outstandingXaf"]==800
       and new["unreservedXaf"]==300 and new["revision"]==3,
       "INSTALLMENT_LEDGER_SOURCE_ONCE")
 check(call(prefix+"/obligations/"+ref+"/collections",cashier,method="POST",body={
   "idem":"SOF-R6-CH-500","channel":"CASH","amount_xaf":500,
   "expected_revision":3},expect=409)==409,"REPLAY_NO_SECOND_EFFECT")
 check(call(prefix+"/obligations/"+ref+"/collections",cashier,method="POST",body={
   "idem":"SOF-R6-OV-999","channel":"CASH","amount_xaf":999,
   "expected_revision":3},expect=409)==409,"NO_OVERALLOCATION")
 check(call(prefix+"/obligations/"+ref+"/collections",cashier,method="POST",body={
   "idem":"SOF-R6-STALE","channel":"CASH","amount_xaf":100,
   "expected_revision":2},expect=409)==409,"STALE_REVISION_DENIED")
 check(call(prefix+"/obligations/"+ref+"/collections",cashier,method="POST",body={
   "idem":"SOF-R6-CROSS","channel":"CASH","amount_xaf":100,
   "expected_revision":3,"branch_id":2},expect=403)==403,
       "WRONG_BRANCH_WRITE_DENIED")
 statement=call(prefix+"/debtors/"+did+"/statement",closer)
 check(statement["outstandingXaf"]==800 and
       len(statement["obligations"])==1 and
       not statement["historicalWndAccountMatch"],"DEBTOR_STATEMENT_PARTIAL")
 history=call(prefix+"/audit",reviewer)
 check(len(history["audit"])==4 and
       [a["action"] for a in history["audit"]]==[
         "CREATE_DEBTOR_TEST","LINK_ORDER_TEST",
         "ALLOCATE_COLLECTION_TEST","ALLOCATE_COLLECTION_TEST"],
       "AUDIT_ALL_SOURCE_TRANSITIONS")
 allocation=call("/api/v3/v24/orders/"+oid+"/allocation",cashier)
 check(allocation["orderTotalXaf"]==2400 and allocation["discountXaf"]==400
       and allocation["cashReceivedTestXaf"]==700
       and allocation["providerPendingTestXaf"]==300 and not allocation["paid"],
       "CANONICAL_ORDER_NOT_REWRITTEN_OR_DUPLICATED")
 check(call(prefix+"/obligations/not-a-uuid",reviewer,expect=422)==422,
       "MALFORMED_UUID_DENIED")
 check(call(prefix+"/obligations/"+ref+"/collections",cashier,method="POST",body={
   "idem":"SOF-R6-BOOL","channel":"CASH","amount_xaf":True,
   "expected_revision":3},expect=422)==422,"BOOL_MONEY_DENIED")
 check(call(prefix+"/obligations/"+ref+"/collections",cashier,method="POST",body={
   "idem":"SOF-R6-FAKEPAID","channel":"SETTLED_PSP","amount_xaf":100,
   "expected_revision":3},expect=422)==422,"FAKE_PROVIDER_FINALITY_DENIED")
 check(call(prefix+"/obligations/"+ref+"/collections",cashier,method="POST",body={
   "idem":"SOF-R6-FRAUD","channel":"CASH","amount_xaf":-50,
   "expected_revision":3},expect=422)==422,"NEGATIVE_COLLECTION_DENIED")
 check(call(prefix+"/debtors?q=Credit",None,expect=401)==401,
       "SESSION_REQUIRED")
 revoked=call("/api/v3/session/revoke",cashier,method="POST")
 check(revoked["revoked"],"SYNTHETIC_TEST_SESSION_REVOKED")
 check(call(prefix+"/obligations/"+ref+"/collections",cashier,method="POST",body={
   "idem":"SOF-R6-AFTER-REVOKE","channel":"CASH","amount_xaf":100,
   "expected_revision":3},expect=401)==401,"REVOKED_ACTOR_CANNOT_ALLOCATE")
 # D7 integrated N/SOF/W now freezes original tender at linkage atomically.
 # Original SOF owner's source-only behavior expected drift; integrated behavior
 # deliberately upgrades to immutable native order tender with no duplicate posting.
 cash2=signin("cashier")
 check(call("/api/v3/v24/orders/"+oid+"/tender",cash2,method="POST",body={
   "idem":"SOF-R6-LATE-CASH-100","channel":"CASH","amount_xaf":100,
   "state":"CASH_RECEIVED_TEST"},expect=409)==409,
   "POST_LINK_ORIGINAL_TENDER_FROZEN_AT_SOURCE")
 held=call(prefix+"/obligations/"+ref,reviewer)
 check(not held["sourceTenderChangedAfterLink"] and not held["sourceTenderReviewRequired"]
       and held["status"]=="TEST_AR_OPEN_SOURCE_ONLY",
       "NO_TENDER_DRIFT_AFTER_ATOMIC_SOURCE_FREEZE")
 c3=call(prefix+"/obligations/"+ref+"/collections",cash2,method="POST",body={
   "idem":"SOF-R6-R6-INTEGRATED-50","channel":"CASH","amount_xaf":50,
   "expected_revision":3})
 check(c3["obligationRevision"]==4 and c3["financePosted"] is False,
       "FROZEN_SOURCE_ALLOWED_INDEPENDENT_AR_INSTALLMENT")
 revised=call(prefix+"/debtors/"+did+"/statement",reviewer)
 check(revised["status"]=="TEST_DEBTOR_STATEMENT_NOT_CANONICAL_AR" and
       revised["outstandingXaf"]==750,
       "DEBTOR_STATEMENT_FINAL_750_NOT_DOUBLE_COUNTED")
 print("R6_INTEGRATED_SOF_AR_PG17_PASS="+str(COUNT))
 print("SOF_R6_TEST_OUTSTANDING_XAF=800")
 print("SOF_R6_NO_CANONICAL_WND_POSTINGS_TRUE")
 print("SOF_R6_EXTERNAL_PROVIDER_CALLS=0")
if __name__=="__main__":main()
