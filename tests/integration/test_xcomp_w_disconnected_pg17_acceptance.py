"""W future-offline source policy tests; NO real PostgreSQL is opened."""
from dataclasses import replace
import pytest
from core.api.restaurant.local_first_lan_router import ServerIssuedScope,LANAccessDenied,admit_lan
from core.domain.restaurant.local_first_shift_session import ShiftIntent,ShiftDenied,admit_shift
from core.domain.restaurant.local_first_stock_draft import Draft,DraftDenied,advance,post_as_finance
from core.domain.restaurant.local_first_receipt_service import FinanceReadback,ReceiptDenied,cash_receipt,provider_paid
A=ServerIssuedScope(910001,5,"cashier","local-A",True,True,False,True,"cash.write")
def test_lan_positive_source_contract():
 assert admit_lan(A,tenant=910001,branch=5,action="cash.write")==A
@pytest.mark.parametrize("delta",[
 {"pc5_verified":False},{"member_active":False},{"revoked":True},
 {"tls_verified":False},{"tenant_id":910002},{"branch_id":6},
 {"action":"platform.issue"},{"node_id":""}])
def test_lan_negative(delta):
 with pytest.raises(LANAccessDenied):admit_lan(replace(A,**delta),tenant=910001,branch=5,action="cash.write")
def test_shift_separate_server_writer():
 class Allow:
  def require_writer(self,**kw):
   assert kw["tenant_id"]==910001
 class Deny:
  def require_writer(self,**kw):raise PermissionError("FENCED")
 item=ShiftIntent(910001,5,"pc5-s1","DAY","order-1")
 assert admit_shift(item,Allow())==item
 with pytest.raises(ShiftDenied):admit_shift(item,Deny())
 with pytest.raises(ShiftDenied):admit_shift(item,object())
def test_draft_revision_never_finance_commit():
 d=Draft(910001,5,"stock-1",0)
 assert advance(d,tenant_id=910001,branch_id=5,expected_revision=0).revision==1
 with pytest.raises(DraftDenied):advance(d,tenant_id=910002,branch_id=5,expected_revision=0)
 with pytest.raises(DraftDenied):advance(d,tenant_id=910001,branch_id=5,expected_revision=1)
 with pytest.raises(DraftDenied):post_as_finance(d)
def test_finance_cash_not_provider_finality():
 r=FinanceReadback(910001,5,"local-A",4,"entry-1",True,True)
 assert "entry-1" in cash_receipt(r,tenant_id=910001,branch_id=5,node_id="local-A",epoch=4)
 with pytest.raises(ReceiptDenied):cash_receipt(replace(r,committed=False),tenant_id=910001,branch_id=5,node_id="local-A",epoch=4)
 with pytest.raises(ReceiptDenied):provider_paid(r)
