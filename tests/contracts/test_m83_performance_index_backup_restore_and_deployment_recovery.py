from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest

from core.domain.finance.m6_acceptance import EXPECTED_HEAD
from core.domain.finance.performance_recovery_contract import FinancialRecoveryFingerprint, PerformanceRecoveryError, PerformanceRecoveryEvidence, QueryPlanEvidence
from core.domain.finance.performance_recovery_service import validate_operator_runbook, validate_query_plan, validate_recovery_evidence
from scripts.verify_m83_performance_recovery import _payment_fixture

ROOT=Path(__file__).resolve().parents[2]


def fingerprint(digest="a"*32):
    return FinancialRecoveryFingerprint(EXPECTED_HEAD,{"financial_events":2},{"financial_events":digest},{"debit":"10","credit":"10"})


def plan(indexes=("ix_financial_events_source",)):
    return QueryPlanEvidence("event_source","financial_events",("Index Scan",),indexes,"0.1","0.2",1)


def test_contract_freezes_schema_neutral_recovery_boundary():
    contract=json.loads((ROOT/"contracts/finance/v1/m83_performance_index_backup_restore_and_deployment_recovery.json").read_text(encoding="utf-8"))
    assert contract["source_checkpoint"]["commit"]=="7f240cb"
    assert contract["canonical_head"]==EXPECTED_HEAD
    assert contract["migration"] is False
    assert contract["backup_restore"]["structural_restore_alone_is_sufficient"] is False
    assert contract["rollback_rehearsal"]["populated_financial_history_downgrade_forbidden"] is True
    assert contract["boundaries"]["live_cutover_owner"]=="R6"


def test_financial_fingerprint_is_deterministic_and_order_independent():
    first=FinancialRecoveryFingerprint(EXPECTED_HEAD,{"a":1,"b":2},{"a":"a"*32,"b":"b"*32},{"x":"1","y":"2"})
    second=FinancialRecoveryFingerprint(EXPECTED_HEAD,{"b":2,"a":1},{"b":"b"*32,"a":"a"*32},{"y":"2","x":"1"})
    assert first.semantic_fingerprint==second.semantic_fingerprint


def test_restore_difference_fails_closed():
    evidence=PerformanceRecoveryEvidence({"financial_events":2},(plan(),),fingerprint(),fingerprint("b"*32),EXPECTED_HEAD,EXPECTED_HEAD)
    with pytest.raises(PerformanceRecoveryError) as raised: validate_recovery_evidence(evidence)
    assert raised.value.code=="financial_restore_mismatch"


def test_query_plan_requires_real_index_evidence():
    with pytest.raises(PerformanceRecoveryError) as raised: validate_query_plan(plan(()))
    assert raised.value.code=="required_index_not_used"


def test_complete_recovery_evidence_passes():
    selected=fingerprint()
    evidence=PerformanceRecoveryEvidence({"financial_events":2},(plan(),),selected,selected,EXPECTED_HEAD,EXPECTED_HEAD)
    validate_recovery_evidence(evidence)


def test_schema_neutral_persistence_markers():
    source=(ROOT/"core/persistence/m83_performance_recovery_hardening.py").read_text(encoding="utf-8")
    for marker in ("SCHEMA_NEUTRAL = True","MIGRATION = None","WRITES_DEVELOPMENT_DATABASE = False","FABRICATES_FINANCIAL_HISTORY = False","CUTOVER_AUTHORIZED = False"):
        assert marker in source
    assert not tuple((ROOT/"alembic_neutral/versions").glob("m83_*.py"))


def test_operator_runbook_is_complete(): validate_operator_runbook(ROOT)


def test_verifier_has_backup_equivalence_and_plan_gates():
    source=(ROOT/"scripts/verify_m83_performance_recovery.py").read_text(encoding="utf-8")
    for marker in ("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)","pg_dump","pg_restore","financial_equivalence=PASS","rollback_rehearsal=PASS","operator_recovery=PASS","schema_neutral=PASS"):
        assert marker in source


def test_event_to_journal_plan_uses_accepted_m24_link_authority():
    source=(ROOT/"scripts/verify_m83_performance_recovery.py").read_text(encoding="utf-8")
    assert '"journal_event_trace","journal_entry_event_links"' in source
    assert "FROM journal_entry_event_links WHERE tenant_id=:tenant AND financial_event_id=:event" in source
    assert '"journal_entry_event_links"' in source
    assert 'FROM journal_event_links' not in source


def test_public_package_and_gate_artifacts_exist():
    assert (ROOT/"XBOS_M8_3_RUN_ACCEPTANCE.cmd").is_file()
    assert (ROOT/"XBOS_M8_3_INSTALL_AND_VERIFY.txt").is_file()


def test_volume_payment_fixture_has_deterministic_valid_lifecycle_time():
    provider=UUID("83000000-0000-0000-0000-000000000001")
    account=UUID("83000000-0000-0000-0000-000000000002")
    first=_payment_fixture(1,1,provider,account,1000,0)
    repeated=_payment_fixture(1,1,provider,account,1000,0)
    intent,attempt,processing,succeeded,settlement,confirmed=first
    assert first==repeated
    assert intent.occurred_at < attempt.occurred_at < processing.occurred_at
    assert processing.occurred_at < succeeded.occurred_at < settlement.occurred_at < confirmed.occurred_at
    assert confirmed.occurred_at < intent.expires_at
    assert attempt.timeout_at <= intent.expires_at
    assert settlement.value_date==intent.business_date
