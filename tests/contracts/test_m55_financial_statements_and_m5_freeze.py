from __future__ import annotations
import json
from dataclasses import replace
from datetime import date,datetime,timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID
import pytest
from core.domain.finance.m5_acceptance import EXPECTED_HEAD,validate_release_manifest
from core.domain.finance.statement_contract import FinancialStatementError,FinancialStatementQuery
from core.domain.finance.statement_service import FinancialStatementService

ROOT=Path(__file__).resolve().parents[2];BASE=datetime(2026,8,31,23,59,tzinfo=timezone.utc)
def query(kind="customer",**changes):
    values=dict(tenant_id=1,organization_unit_id=2,party_id=UUID(int=55),statement_type=kind,currency_code="xaf",period_start=date(2026,8,1),period_end=date(2026,8,31),as_of=BASE);values.update(changes);return FinancialStatementQuery(**values)
class FakeRepository:
    @staticmethod
    def rows(session,selected):
        return Decimal("20"),[
            {"occurred_at":datetime(2026,8,2,tzinfo=timezone.utc),"sequence":1,"line_type":"obligation","reference":"A","debit":Decimal("100"),"credit":Decimal("0")},
            {"occurred_at":datetime(2026,8,3,tzinfo=timezone.utc),"sequence":2,"line_type":"allocation","reference":"B","debit":Decimal("0"),"credit":Decimal("35")},]
class FakeService(FinancialStatementService):repository=FakeRepository

def test_contract_is_schema_neutral():
    data=json.loads((ROOT/"contracts/finance/v1/m55_financial_statements_and_m5_freeze.json").read_text());assert data["canonical_head"]==EXPECTED_HEAD and data["migration"] is False
def test_release_manifest_semantics_and_lineage():assert validate_release_manifest(ROOT)==6
@pytest.mark.parametrize("kind",["customer","supplier"])
def test_statement_types(kind):assert query(kind).statement_type==kind
def test_invalid_statement_type():
    with pytest.raises(FinancialStatementError) as raised:query("employee")
    assert raised.value.code=="invalid_statement_type"
def test_period_order():
    with pytest.raises(FinancialStatementError) as raised:query(period_start=date(2026,9,1))
    assert raised.value.code=="invalid_period"
def test_as_of_timezone():
    with pytest.raises(FinancialStatementError) as raised:query(as_of=BASE.replace(tzinfo=None))
    assert raised.value.code=="timezone_required"
def test_as_of_cannot_precede_period():
    with pytest.raises(FinancialStatementError) as raised:query(as_of=datetime(2026,8,1,tzinfo=timezone.utc))
    assert raised.value.code=="as_of_precedes_period"
@pytest.mark.parametrize("tenant,organization",[(0,2),(1,0)])
def test_positive_scope(tenant,organization):
    with pytest.raises(FinancialStatementError) as raised:query(tenant_id=tenant,organization_unit_id=organization)
    assert raised.value.code=="invalid_scope"
def test_currency_normalized():assert query().currency_code=="XAF"
def test_statement_arithmetic_and_running_balance():
    report=FakeService.generate(None,query());assert report.opening_balance==20 and report.total_debits==100 and report.total_credits==35 and report.closing_balance==85 and [x.running_balance for x in report.lines]==[120,85]
def test_statement_is_immutable_tuple():assert isinstance(FakeService.generate(None,query()).lines,tuple)
def test_statement_digest_is_deterministic():assert FakeService.generate(None,query()).semantic_sha256==FakeService.generate(None,query()).semantic_sha256
def test_party_changes_digest():assert FakeService.generate(None,query()).semantic_sha256!=FakeService.generate(None,query(party_id=UUID(int=56))).semantic_sha256
def test_repository_is_read_only_and_tenant_scoped():
    source=(ROOT/"core/domain/finance/statement_repository.py").read_text();assert "INSERT " not in source and "UPDATE " not in source and "DELETE " not in source and "o.tenant_id=:tenant" in source
def test_repository_orders_deterministically():assert "ORDER BY occurred_at,sequence,reference" in (ROOT/"core/domain/finance/statement_repository.py").read_text()
def test_persistence_marker_has_no_schema():
    source=(ROOT/"core/persistence/m55_financial_lifecycle_exit.py").read_text();assert "SCHEMA_NEUTRAL=True" in source and "WRITES_NEW_TABLES=False" in source
def test_verifier_has_exit_markers():
    source=(ROOT/"scripts/verify_m55_financial_lifecycle_exit.py").read_text()
    for marker in ("statements=PASS","m50_m54=PASS","manifest=PASS","development=PASS","dropped=true"):assert marker in source
