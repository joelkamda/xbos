"""R7 real Chromium→React→FastAPI→PG17, five owner returns unified.
No external requests, real WND, fiscal printing, PSP, or genuine PC5.
"""
import json
from playwright.sync_api import sync_playwright,expect
N=0
def ck(v,label):
 global N
 if not v:raise AssertionError("R7_BROWSER_"+label)
 N+=1
def main():
 js=[];external=[]
 with sync_playwright() as pw:
  browser=pw.chromium.launch(headless=True,args=[
      "--no-sandbox","--disable-gpu","--disable-dev-shm-usage"])
  page=browser.new_page(viewport={"width":1024,"height":860},accept_downloads=True)
  page.on("pageerror",lambda e:js.append(str(e)))
  page.on("request",lambda r:external.append(r.url) if not
        r.url.startswith("http://127.0.0.1:8791/") else None)
  ck(page.goto("http://127.0.0.1:8791/rehearsal/v24").status==200,"REAL_REACT_HTTP")
  expect(page.get_by_role("heading",name="Debtor / Accounts receivable")).to_be_visible()
  ck(page.get_by_role("button",name="Request duplicate TEST receipt").is_disabled(),
     "NO_ANONYMOUS_BUSINESS_ACTION")
  page.get_by_role("button",name="Switch to French").click()
  expect(page.get_by_role("heading",name="Débiteur / Comptes clients")).to_be_visible()
  ck(page.locator("main").get_attribute("lang")=="fr","FRENCH_WORKFLOW")
  page.get_by_role("button",name="Passer en anglais").click()
  ck(page.locator("main").get_attribute("lang")=="en","ENGLISH_WORKFLOW")
  def login(role):
   page.locator("#v24-role").select_option(role)
   page.locator("#v24-password").fill("V24-ONLY-"+role+"-synthetic")
   page.get_by_role("button",name="Sign in").click()
   expect(page.get_by_test_id("v24-active-role")).to_contain_text(role.capitalize(),timeout=20000)
   ck(True,"SIGNED_SYNTHETIC_"+role)
  def do(label,contains=None):
   page.get_by_role("button",name=label,exact=True).click()
   expect(page.get_by_test_id("v24-status")).to_contain_text(label+" — TEST action completed",timeout=24000)
   if contains:expect(page.get_by_test_id("v24-response")).to_contain_text(contains,timeout=12000)
   ck(True,label.upper().replace(" ","_").replace("/","_"))
  login("merchant")
  page.get_by_label("Product name").fill("Synthetic R7 herbal mocktail")
  do("Create draft")
  do("Set Main / VIP / Bar prices",'"priceRevisions"')
  do("Request review",'"priceRevisions"')
  ck("Zone price revisions: " in page.get_by_test_id("v24-price-revisions").text_content(),
     "FE_PASSES_PRICE_CAS_REVISIONS")
  login("reviewer")
  do("Publish to native catalog",'"r7NativePkPreflight"')
  check=page.get_by_test_id("v24-response").text_content() or ""
  ck('"genuinePc5": false' in check and '"nativeCatalog": true' in check,
     "PK_AND_PA_NO_FALSE_PC5")
  login("cashier")
  do("Save native POS order",'"orderId"')
  ck("NONE" not in page.get_by_test_id("v24-order-id").text_content(),
     "ACTUAL_ORDER_IN_PG17")
  login("merchant")
  do("Apply TEST discount")
  do("Request duplicate TEST receipt",'"requestId"')
  login("reviewer")
  do("Approve duplicate preview",'"PREVIEW_APPROVED_TEST"')
  login("cashier")
  do("View approved duplicate preview",'"printed": false')
  login("merchant")
  page.get_by_label("Debtor display name").fill("Synthetic R7 Debtor UI")
  do("Create TEST debtor")
  do("Link this unpaid order to debtor")
  login("cashier")
  page.get_by_label("TEST installment amount").fill("100")
  do("Record TEST installment",'"CASH_RECEIVED_TEST"')
  login("reviewer")
  do("Read linked A/R",'"cashTestAllocatedXaf": 100')
  do("Debtor statement")
  do("A/R audit")
  page.get_by_label("Shift",exact=True).select_option("DAY")
  do("Read native daily report",'"shift": "DAY"')
  snapshot=json.loads(page.get_by_test_id("v24-response").text_content() or "{}")
  recorded=sum(int(x["amount"]) for x in snapshot["tenderEvents"]
        if x["status"]=="CASH_RECEIVED_TEST" and x["channel"]=="CASH")
  page.get_by_label("Opening cash (XAF)").fill("100")
  page.get_by_label("Physically counted cash (XAF)").fill(str(100+recorded+55))
  do("Preview signed cash variance",'"varianceSignedXaf": 55')
  with page.expect_download(timeout=20000) as dl:
   page.get_by_role("button",name="Download TEST daily statement").click()
  ck(dl.value.suggested_filename=="WND-V3-TEST-daily-shift.csv","COMPLETE_DAILY_TEST_CSV")
  ck("NOT_OFFICIAL_LEDGER" in dl.value.path().read_text(encoding="utf-8"),
     "NO_OFFICIAL_LEDGER_MISREPRESENTATION")
  page.set_viewport_size({"width":320,"height":720})
  ck(page.get_by_role("button",name="View approved duplicate preview").is_visible(),
     "FE_320PX_CUSTODY_UI")
  ck(not js,"NO_JAVASCRIPT_EXCEPTIONS")
  ck(not external,"ZERO_BROWSER_EXTERNAL_REQUESTS")
  browser.close()
 print("R7_UNIFIED_CHROMIUM_API_PG17_PASS="+str(N))
 print("R7_BROWSER_REAL_PC5=False")
 print("R7_BROWSER_PRINTED=False")
if __name__=="__main__":main()
