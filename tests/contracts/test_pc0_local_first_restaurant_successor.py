"""Prospective v2 source gate; does not amend historical PC0."""
import copy
import json
import shutil
from pathlib import Path
import pytest
from core.platform.local_first_restaurant_architecture_successor import (
    validate_local_first_restaurant_successor, ProspectivePC0Denied, CONTRACT_REL)

ROOT = Path(__file__).resolve().parents[2]

def test_prospective_source_qualified_without_pc0_bypass():
    result=validate_local_first_restaurant_successor(ROOT)
    assert result["historical_pc0_intact"]
    assert result["status"]=="PROSPECTIVE_SOURCE_QUALIFIED_NOT_HOSTED"
    assert result["real_postgres_or_offline_certified"] is False

@pytest.fixture
def sandbox(tmp_path):
    contract=json.loads((ROOT/CONTRACT_REL).read_text(encoding="utf-8"))
    paths=[CONTRACT_REL,*contract["historical_pc0_sha256"],*contract["module"]["source_files"]]
    for rel in paths:
        target=tmp_path/rel
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/rel,target)
    return tmp_path

@pytest.mark.parametrize("mutation,code",[
    (("dependency_policy","default","allow"),"PROSPECTIVE_DEPENDENCY_LAW_WEAKENED"),
    (("dependency_policy","wildcard_exceptions",True),"PROSPECTIVE_DEPENDENCY_LAW_WEAKENED"),
    (("module","owner","Unknown Owner"),"RESTAURANT_MODULE_OWNER_DRIFT"),
    (("module","source_roots",["core/api/orders"]),"RESTAURANT_MODULE_OWNER_DRIFT"),
    (("out_of_scope",None,[]),"PROSPECTIVE_OPERATIVE_BOUNDARY_CHANGED"),
])
def test_forbidden_contract_changes_fail_closed(sandbox,mutation,code):
    path=sandbox/CONTRACT_REL
    c=json.loads(path.read_text(encoding="utf-8"))
    section,key,value=mutation
    if key is None:c[section]=value
    else:c[section][key]=value
    path.write_text(json.dumps(c),encoding="utf-8")
    with pytest.raises(ProspectivePC0Denied,match=code):
        validate_local_first_restaurant_successor(sandbox)

def test_historical_pc0_tamper_denied(sandbox):
    f=sandbox/"contracts/platform/v1/pc0_module_map.json"
    f.write_bytes(f.read_bytes()+b" ")
    with pytest.raises(ProspectivePC0Denied,match="HISTORICAL_PC0_MODIFIED"):
        validate_local_first_restaurant_successor(sandbox)

def test_source_drift_denied(sandbox):
    f=sandbox/"core/api/restaurant/local_first_lan_router.py"
    f.write_bytes(f.read_bytes()+b"\n")
    with pytest.raises(ProspectivePC0Denied,match="RESTAURANT_SOURCE_HASH_DRIFT"):
        validate_local_first_restaurant_successor(sandbox)

def test_unreviewed_restaurant_path_denied(sandbox):
    (sandbox/"core/domain/restaurant/unreviewed.py").write_text("x=1\n")
    with pytest.raises(ProspectivePC0Denied,match="NEW_RESTAURANT_SOURCE_UNREVIEWED"):
        validate_local_first_restaurant_successor(sandbox)

def test_untrusted_direct_import_denied_even_with_matching_hash(sandbox):
    import hashlib
    f=sandbox/"core/api/restaurant/local_first_lan_router.py"
    f.write_text(f.read_text(encoding="utf-8")+"\nfrom core.platform.security_authority import service\n",encoding="utf-8")
    cpath=sandbox/CONTRACT_REL
    c=json.loads(cpath.read_text(encoding="utf-8"))
    c["module"]["source_files"]["core/api/restaurant/local_first_lan_router.py"]=hashlib.sha256(f.read_bytes()).hexdigest()
    cpath.write_text(json.dumps(c),encoding="utf-8")
    with pytest.raises(ProspectivePC0Denied,match="RESTAURANT_SOURCE_PROVENANCE_DRIFT"):
        validate_local_first_restaurant_successor(sandbox)


def test_historical_contract_and_v1_file_cannot_be_jointly_rewritten(sandbox):
    import hashlib
    rel="contracts/platform/v1/pc0_module_map.json"
    f=sandbox/rel
    f.write_bytes(f.read_bytes()+b" ")
    contract=sandbox/CONTRACT_REL
    c=json.loads(contract.read_text(encoding="utf-8"))
    c["historical_pc0_sha256"][rel]=hashlib.sha256(f.read_bytes()).hexdigest()
    contract.write_text(json.dumps(c),encoding="utf-8")
    with pytest.raises(ProspectivePC0Denied,match="HISTORICAL_PC0_INVENTORY_DRIFT"):
        validate_local_first_restaurant_successor(sandbox)
