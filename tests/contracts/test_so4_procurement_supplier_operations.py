from __future__ import annotations
import json
from dataclasses import replace
from datetime import datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID
import pytest

ROOT=Path(__file__).resolve().parents[2]
from shared_operations.so4 import *
from shared_operations.so4.service import SO4AuthorityError

NOW=datetime(2026,8,14,tzinfo=timezone.utc); PARTY=UUID(int=1); REL=UUID(int=2); UNIT=UUID(int=3); STOCK=UUID(int=4); ORDER=UUID(int=5); LINE=UUID(int=6); RECEIPT=UUID(int=7)

class Repo:
    def __init__(self):
        self.orders={ORDER:PurchaseOrder(ORDER,1,"po-1",PARTY,REL,ProcurementStatus.ORDERED,OverReceiptPolicy.FORBID,(PurchaseOrderLine(LINE,1,LineType.STOCK,"unit",UNIT,STOCK,10,0),),NOW,1)};self.receipts={};self.commands={};self.calls=0
    def request(self,*a):return None
    def order(self,t,p):return self.orders.get(p) if t==1 else None
    def create_order(self,c,*a):return self.orders[ORDER]
    def create_request(self,c,lines,p,f):return PurchaseRequest(p,c.tenant_id,c.request_code,ProcurementStatus.DRAFT,lines,c.expected_by,1)
    def transition(self,c,f,is_order):
        value=self.orders.get(c.resource_public_id)
        if not value or value.row_version!=c.expected_version:return None
        self.orders[c.resource_public_id]=replace(value,status=c.to_status,row_version=value.row_version+1);return self.orders[c.resource_public_id]
    def begin_receipt(self,c,p,f):
        self.calls+=1
        if c.command_key in self.commands and self.commands[c.command_key]!=f:raise SO4AuthorityError("SO4_COMMAND_CONFLICT","conflict","Command key was reused with different content")
        self.commands.setdefault(c.command_key,f)
        if c.command_key in self.receipts:return self.receipts[c.command_key],()
        return None,({"order_line_public_id":LINE,"quantity":c.lines[0].quantity,"outstanding":10,"policy":"forbid","line_type":"stock","atomic_unit_public_id":UNIT,"location_public_id":STOCK},)
    def complete_receipt(self,c,p,m):
        result=ProcurementReceipt(p,1,ORDER,c.receipt_code,c.occurred_at,c.lines,tuple(x[1] for x in m));self.receipts[c.command_key]=result;return result

class Inventory:
    def __init__(self):self.calls=[]
    def receive(self,c):
        self.calls.append(c);return None,SimpleNamespace(public_id=UUID(int=90+len(self.calls)))

def authority(repo=None,inventory=None,tenant=1,auth=True):
    repo=repo or Repo();inventory=inventory or Inventory()
    owned=lambda pid:SimpleNamespace(id=10,tenant_id=tenant,public_id=pid)
    relationship=lambda t,p:SimpleNamespace(id=20,tenant_id=tenant,public_id=p,party_public_id=PARTY,relationship_type_code="supplier",status="active")
    return SO4Authority(repo,party_resolver=lambda t,p:owned(p),relationship_resolver=relationship,atomic_unit_resolver=lambda t,p:owned(p),stock_location_resolver=lambda t,p:owned(p),inventory_authority=inventory,authorize=lambda *x:auth,approval_validator=lambda *x:True,public_id_factory=lambda:RECEIPT),repo,inventory

def test_authority_and_legacy_decisions_are_explicit():
    base=ROOT/"contracts/shared_operations/v1";a=json.loads((base/"so4_authority.json").read_text());d=json.loads((base/"so4_legacy_adoption_manifest.json").read_text())
    assert a["supplier_authority"]=="PC2_PARTY_PLUS_SO2_RELATIONSHIP" and a["inventory_authority"]=="SO3_PUBLIC_CONTRACT_REUSED"
    assert {x["classification"] for x in d["decisions"]}=={"ADOPT","MAP","BRIDGE","PRESERVE","RETIRE_LATER"}

def test_migration_has_tenant_qualified_predecessor_fks_and_no_finance():
    sql=(ROOT/"alembic_neutral/sql/so4_procurement_supplier_operations_up.sql").read_text()
    for target in ("parties","so2_operational_relationships","atomic_units","so3_stock_locations"):
        assert f"REFERENCES public.{target}(tenant_id,id)" in sql
    assert "REFERENCES public.so3_stock_locations(id)" not in sql
    assert not any(x in sql.lower() for x in ("financial_events","journal_entries","obligations","settlements","payments"))

def test_supplier_party_relationship_atomic_and_stock_are_tenant_scoped():
    a,_,_=authority(tenant=2)
    cmd=CreatePurchaseOrder("k",1,"PO",PARTY,REL,(ProcurementLineInput(1,LineType.STOCK,"x",1,UNIT,STOCK),))
    with pytest.raises(SO4AuthorityError,match="SO4_SUPPLIER_PARTY_NOT_FOUND"):a.create_order(cmd)

def test_invalid_lifecycle_and_pc5_approval_fail_closed():
    a,repo,_=authority();cmd=TransitionProcurement("t",1,ORDER,1,ProcurementStatus.CLOSED,"close",NOW)
    with pytest.raises(SO4AuthorityError,match="SO4_INVALID_STATE_TRANSITION"):a.transition_order(cmd)
    repo.orders[ORDER]=replace(repo.orders[ORDER],status=ProcurementStatus.SUBMITTED)
    a.approval_validator=lambda *x:False
    with pytest.raises(SO4AuthorityError,match="SO4_APPROVAL_REQUIRED"):a.transition_order(replace(cmd,to_status=ProcurementStatus.APPROVED))

def test_partial_receipt_is_exact_and_replay_does_not_double_apply_stock():
    a,_,inventory=authority();cmd=ReceivePurchaseOrder("receipt-1",1,ORDER,"GR-1",(ReceiptLineInput(LINE,4),),NOW)
    first=a.receive(cmd);second=a.receive(cmd)
    assert first==second and len(inventory.calls)==1 and inventory.calls[0].quantity==4
    assert inventory.calls[0].source_type=="so4-procurement"

@pytest.mark.parametrize("change",[
    lambda c:replace(c,occurred_at=c.occurred_at+timedelta(microseconds=1)),
    lambda c:replace(c,receipt_code="GR-CHANGED"),
    lambda c:replace(c,lines=(ReceiptLineInput(LINE,5),)),
    lambda c:replace(c,source_reference="changed-source"),
])
def test_same_receipt_key_with_any_changed_fingerprinted_content_conflicts(change):
    a,_,inventory=authority();original=ReceivePurchaseOrder("receipt-conflict",1,ORDER,"GR-1",(ReceiptLineInput(LINE,4),),NOW,source_reference="source-1")
    a.receive(original)
    with pytest.raises(SO4AuthorityError,match="SO4_COMMAND_CONFLICT"):a.receive(change(original))
    assert len(inventory.calls)==1

def test_receipt_join_locks_only_canonical_so4_line_and_serializes_on_order():
    source=(ROOT/"shared_operations/so4/sql_repository.py").read_text()
    joined=next(line for line in source.splitlines() if "LEFT JOIN locations loc" in line and "FOR UPDATE" in line)
    assert "FOR UPDATE OF l" in joined
    assert "FOR UPDATE\"" not in joined and "FOR UPDATE OF u" not in joined and "FOR UPDATE OF s" not in joined and "FOR UPDATE OF loc" not in joined
    order_lock=source.index("SELECT * FROM so4_purchase_orders WHERE tenant_id=:t AND public_id=:p FOR UPDATE")
    line_lock=source.index("FOR UPDATE OF l")
    assert order_lock < line_lock

def test_sequential_receipts_recompute_outstanding_and_cannot_over_receive():
    a,repo,_=authority()
    first=ReceivePurchaseOrder("first",1,ORDER,"GR-1",(ReceiptLineInput(LINE,6),),NOW)
    a.receive(first)
    repo.orders[ORDER]=replace(repo.orders[ORDER],lines=(replace(repo.orders[ORDER].lines[0],received_quantity=6),),status=ProcurementStatus.PARTIALLY_RECEIVED)
    original=repo.begin_receipt
    def current_plan(command,public_id,fingerprint):
        replay,plan=original(command,public_id,fingerprint)
        if plan:plan=({**plan[0],"outstanding":4},)
        return replay,plan
    repo.begin_receipt=current_plan
    with pytest.raises(SO4AuthorityError,match="SO4_OVER_RECEIPT_FORBIDDEN"):
        a.receive(ReceivePurchaseOrder("second",1,ORDER,"GR-2",(ReceiptLineInput(LINE,5),),NOW))

def test_over_receipt_is_governed_and_negative_quantities_fail():
    a,repo,_=authority()
    with pytest.raises(SO4AuthorityError,match="SO4_INVALID_RECEIPT"):a.receive(ReceivePurchaseOrder("bad",1,ORDER,"GR",(ReceiptLineInput(LINE,-1),),NOW))
    with pytest.raises(SO4AuthorityError,match="SO4_OVER_RECEIPT_FORBIDDEN"):a.receive(ReceivePurchaseOrder("over",1,ORDER,"GR",(ReceiptLineInput(LINE,11),),NOW))

def test_permission_denial_is_server_side_and_xa_never_grants_authority():
    a,_,_=authority(auth=False)
    with pytest.raises(SO4AuthorityError,match="SO4_PERMISSION_DENIED"):a.create_request(CreatePurchaseRequest("k",1,"r",(ProcurementLineInput(1,LineType.SERVICE,"consultation",1),)))
    xa=json.loads((ROOT/"contracts/shared_operations/v1/so4_xa_metadata.json").read_text());assert xa["frontend_authorization"]=="NEVER"

def test_two_materially_different_neutral_profiles_use_same_contract():
    base=ROOT/"contracts/shared_operations/v1/examples";retail=json.loads((base/"retail_merchandise_procurement_profile.json").read_text());clinical=json.loads((base/"clinical_service_supply_procurement_profile.json").read_text())
    assert retail["terminology"]!=clinical["terminology"] and retail["service_procurement"] is False and clinical["service_procurement"] is True
    assert "restaurant" not in json.dumps((retail,clinical)).lower()
