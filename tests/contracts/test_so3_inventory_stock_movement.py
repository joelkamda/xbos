import json
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID
import pytest

ROOT=Path(__file__).resolve().parents[2]
from shared_operations.so3 import SO3Authority, SO3AuthorityError, MoveStock, TransferStock
from scripts.verify_so3_inventory_stock_movement import _verify_fk_candidate_keys

def test_contract_boundaries_and_neutral_profiles():
    base=ROOT/"contracts/shared_operations/v1"
    authority=json.loads((base/"so3_authority.json").read_text())
    retail=json.loads((base/"examples/retail_inventory_profile.json").read_text()); clinic=json.loads((base/"examples/clinical_supplies_profile.json").read_text())
    assert authority["financial_valuation"]=="EXCLUDED" and retail["terminology"]!=clinic["terminology"]

def test_migration_adopts_legacy_and_is_append_only():
    sql=(ROOT/"alembic_neutral/sql/so3_inventory_stock_movement_up.sql").read_text()
    assert "ALTER TABLE public.inventory_items" in sql and "ALTER TABLE public.inventory_movements" in sql
    assert "legacy_branch_structural_mappings" in sql and "BEFORE UPDATE OR DELETE" in sql

def test_every_so3_fk_target_has_tenant_scoped_candidate_key():
    sql=(ROOT/"alembic_neutral/sql/so3_inventory_stock_movement_up.sql").read_text()
    _verify_fk_candidate_keys(sql)
    assert sql.count("CONSTRAINT uq_so3_stock_locations_tenant_id UNIQUE(tenant_id,id)")==1
    assert "REFERENCES public.so3_stock_locations(id)" not in sql

def test_stock_location_fk_candidate_key_and_cross_tenant_scope_fail_closed():
    sql=(ROOT/"alembic_neutral/sql/so3_inventory_stock_movement_up.sql").read_text()
    weakened=sql.replace("CONSTRAINT uq_so3_stock_locations_tenant_id UNIQUE(tenant_id,id)","UNIQUE(id)")
    with pytest.raises(RuntimeError,match="SO3_FK_CANDIDATE_KEY_MISSING"):_verify_fk_candidate_keys(weakened)
    weakened=sql.replace("FOREIGN KEY(tenant_id,stock_location_id) REFERENCES public.so3_stock_locations(tenant_id,id)","FOREIGN KEY(stock_location_id) REFERENCES public.so3_stock_locations(id)",1)
    with pytest.raises(RuntimeError,match="SO3_CROSS_TENANT_FK_WEAKENED|SO3_STOCK_LOCATION_FK_COVERAGE"):_verify_fk_candidate_keys(weakened)

def test_cross_tenant_and_authorization_fail_closed():
    unit=UUID(int=1); location=UUID(int=2)
    authority=SO3Authority(SimpleNamespace(),atomic_unit_resolver=lambda tenant,pid: SimpleNamespace(id=1,tenant_id=2,public_id=pid),location_resolver=lambda tenant,pid: None,authorize=lambda *args: True)
    with pytest.raises(SO3AuthorityError) as error: authority.receive(MoveStock("k",1,unit,location,1,"receipt",__import__('datetime').datetime.now(__import__('datetime').timezone.utc),"test"))
    assert error.value.code=="SO3_ATOMIC_UNIT_NOT_FOUND"
    denied=SO3Authority(SimpleNamespace(),atomic_unit_resolver=lambda *x:None,location_resolver=lambda *x:None,authorize=lambda *args:False)
    with pytest.raises(SO3AuthorityError) as error: denied.list_positions(1)
    assert error.value.code=="SO3_PERMISSION_DENIED"

def test_transfer_contract_requires_distinct_locations():
    now=__import__('datetime').datetime.now(__import__('datetime').timezone.utc); value=UUID(int=3)
    authority=SO3Authority(SimpleNamespace(),atomic_unit_resolver=lambda t,p:SimpleNamespace(id=1,tenant_id=t,public_id=p),location_resolver=lambda t,p:SimpleNamespace(id=1,tenant_id=t,public_id=p),authorize=lambda *a:True)
    with pytest.raises(SO3AuthorityError) as error: authority.transfer(TransferStock("k",1,UUID(int=1),value,value,1,"transfer",now,"test"))
    assert error.value.code=="SO3_TRANSFER_SAME_LOCATION"

def test_no_wnd_or_finance_authority_in_active_so3():
    data=b"".join(p.read_bytes().lower() for p in (ROOT/"shared_operations/so3").glob("*.py"))
    assert bytes((87,78,68)).lower() not in data and b"journal_entries" not in data and b"financial_events" not in data
