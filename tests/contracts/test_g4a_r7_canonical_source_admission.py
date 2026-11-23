"""G4-A local/CI provenance and safety admission, no DB, network or live WND."""
from pathlib import Path
import json,shutil
from dataclasses import FrozenInstanceError
from dataclasses import replace
import pytest

from restaurant.g4a_source_admission import (
 G4ASourceAdmissionError,inspect_test_source,require_production_admission,
 REQUIRED_ROOTS,R7_ACCEPTED_REPORT,R6_ACCEPTED_REPORT,
)

ROOT=Path(__file__).resolve().parents[2]
BUNDLE=ROOT/"g4a_testonly"

def test_exact_accepted_r7_sha_index_and_161_connected_checks():
    result=inspect_test_source(BUNDLE)
    assert result.total_checks==161
    assert (result.api_pg17_checks,result.browser_checks)==(123,38)
    assert result.counted_files>=54
    assert not result.production_admitted and not result.canonical_runtime_mounted

def test_nonoperative_cannot_issue_production_authority():
    with pytest.raises(G4ASourceAdmissionError,match="G4A_REAL_PC5"):
        require_production_admission(tenant_id=2,branch_id=1,psp="PRODUCTION")

@pytest.mark.parametrize("mutation",["grade","base","r6_hash","r7_hash","count","pc5","file_missing","file_sha"])
def test_tamper_and_operational_upgrade_always_denied(tmp_path,mutation):
    dst=tmp_path/"bundle";dst.mkdir()
    obj=json.loads((BUNDLE/"R7_SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
    # This is ONLY a copy of the checked manifest + one critical source. Other
    # files are intentionally absent, so no test can accidentally claim PASS.
    if mutation=="grade":obj["source_grade"]="PRODUCTION"
    if mutation=="base":obj["canonical_protected_base"]="0"*40
    if mutation=="r6_hash":obj["accepted_r6_root_sha256"]="0"*64
    if mutation=="r7_hash":obj["accepted_r7_report_sha256"]="0"*64
    if mutation=="count":obj["accepted_r7_checks"]["total"]=999
    if mutation=="pc5":obj["permissions"]["genuine_pc5"]=True
    if mutation=="file_missing":obj["files"].pop(next(iter(REQUIRED_ROOTS)))
    if mutation=="file_sha":
        v=obj["files"][next(iter(REQUIRED_ROOTS))];v["sha256"]="0"*64
    (dst/"R7_SOURCE_MANIFEST.json").write_text(json.dumps(obj),encoding="utf-8")
    with pytest.raises(G4ASourceAdmissionError):
        inspect_test_source(dst)

def test_critical_source_is_in_sha_index():
    manifest=json.loads((BUNDLE/"R7_SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
    assert REQUIRED_ROOTS.issubset(manifest["files"])
    assert manifest["accepted_r6_root_sha256"]==R6_ACCEPTED_REPORT
    assert manifest["accepted_r7_report_sha256"]==R7_ACCEPTED_REPORT

def test_r7_never_automounts_into_canonical_kernel():
    startup=(ROOT/"startup.py").read_text(encoding="utf-8")
    entry=(ROOT/"main.py").read_text(encoding="utf-8")
    kernel=(ROOT/"core/api/kernel_router.py").read_text(encoding="utf-8")
    for candidate in ("g4a_testonly","v24_app","v24_native_api"):
        assert candidate not in startup and candidate not in entry
        assert candidate not in kernel

def test_only_synthetic_postgres_scope_and_no_real_actions():
    src=BUNDLE/"source/backend"
    seed=(src/"rehearsal_v3/seed.py").read_text(encoding="utf-8")
    assert 'DB="v24_native_d7_test"' in seed
    assert "PORT=55449" in seed and '127.0.0.1' in seed
    tables=(src/"v24_init_r7.sql").read_text(encoding="utf-8")
    assert "tenant_id=920002" in tables and "branch_id=1" in tables
    publisher=(src/"rehearsal_v3/v24_native_api.py").read_text(encoding="utf-8")
    assert "require_native_test_publish_grant" in publisher
    assert "guard_synthetic_product_publish" in publisher
    assert "genuinePc5" in publisher

def test_canonical_wnd_finance_and_date_contract_is_still_independent():
    from datetime import date,datetime
    from zoneinfo import ZoneInfo
    from restaurant.wnd_d2_parity_candidate import window_for
    w=window_for(date(2026,11,22),"night")
    assert w.start_utc.isoformat()=="2026-11-22T17:00:00+00:00"
    assert w.end_utc.isoformat()=="2026-11-23T07:00:00+00:00"
