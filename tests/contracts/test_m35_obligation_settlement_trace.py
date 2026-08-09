from datetime import date, datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
from uuid import UUID

import pytest

from core.domain.finance.obligation_trace_contract import (
    ObligationTraceError,
    ObligationTraceNotFound,
    ObligationTraceQuery,
)
from core.domain.finance.obligation_trace_repository import ObligationTraceRepository
from core.domain.finance.obligation_trace_service import ObligationSettlementTraceService
from core.persistence.m35_obligation_trace import (
    PARENT_REVISION,
    SCHEMA_CHANGE,
    TARGET_REVISION,
    TEST_DATABASE_NAME,
)

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = json.loads((ROOT / "contracts/finance/v1/m35_obligation_settlement_trace.json").read_text())
OID = UUID("35000000-0000-0000-0000-000000000101")
STAMP = datetime(2026, 8, 9, 10, tzinfo=timezone.utc)


def test_contract_identity_and_lineage():
    assert CONTRACT["contract_code"] == "XBOS_M35_OBLIGATION_SETTLEMENT_TRACE"
    assert CONTRACT["milestone"] == "M3.5"
    assert CONTRACT["parent_commit"] == "83e2779"
    assert CONTRACT["parent_revision"] == PARENT_REVISION == "m34_obligation_aging_010"
    assert CONTRACT["target_revision"] == TARGET_REVISION == PARENT_REVISION


def test_boundary_is_schema_neutral_and_read_only():
    assert SCHEMA_CHANGE is False and CONTRACT["schema_change"] is False
    assert CONTRACT["authority"] == {
        "write_authority": False, "read_model_only": True, "tenant_scoped": True,
        "public_routes": False, "wnd_writer_switch": False,
    }
    assert TEST_DATABASE_NAME == "xbos_track_b_m35_obligation_trace_test"


def test_acceptance_is_single_fail_fast_gate():
    assert CONTRACT["acceptance_mode"] == "single_fail_fast_gate"


def test_correlation_is_not_misrepresented_as_causation():
    semantics = CONTRACT["evidence_semantics"]
    assert semantics["financial_event_and_journal_correlation"] == "supporting evidence only"
    assert semantics["correlation_does_not_prove_causation"] is True


def test_query_current_mode():
    query = ObligationTraceQuery(tenant_id=35, obligation_public_id=str(OID))
    assert query.obligation_public_id == OID
    assert query.as_of is None and query.as_of_business_date is None


def test_query_historical_mode():
    query = ObligationTraceQuery(35, OID, STAMP, date(2026, 8, 9))
    assert query.as_of == STAMP


@pytest.mark.parametrize("timestamp,business_date", [(STAMP, None), (None, date(2026, 8, 9))])
def test_query_rejects_partial_cutoff(timestamp, business_date):
    with pytest.raises(ObligationTraceError, match="paired"):
        ObligationTraceQuery(35, OID, timestamp, business_date)


def test_query_requires_timezone():
    with pytest.raises(ObligationTraceError, match="timezone-aware"):
        ObligationTraceQuery(35, OID, datetime(2026, 8, 9), date(2026, 8, 9))


def test_query_rejects_invalid_tenant():
    with pytest.raises(ObligationTraceError, match="positive"):
        ObligationTraceQuery(0, OID)


class FakeRepository:
    @staticmethod
    def obligation(session, query):
        if query.tenant_id != 35:
            return None
        return {"id": 7, "public_id": OID, "tenant_id": 35, "organization_unit_id": 351,
                "debtor_party_id": UUID(int=1), "creditor_party_id": UUID(int=2),
                "obligation_type": "trade_receivable", "original_amount": Decimal("100"),
                "currency_code": "XAF", "due_at": STAMP, "occurred_at": STAMP,
                "business_date": STAMP.date(), "correlation_id": UUID(int=9),
                "source_component": "m35.test", "source_record_id": "o1",
                "obligation_state": "partially_satisfied", "row_version": 2}

    @staticmethod
    def lines(*args):
        return [{"line_number": 1, "line_amount": Decimal("100")}]

    @staticmethod
    def states(*args):
        return [{"id": 1, "from_state": None, "to_state": "open"},
                {"id": 2, "from_state": "open", "to_state": "partially_satisfied"}]

    @staticmethod
    def allocations(*args):
        return [{"id": 10, "public_id": UUID(int=10), "allocation_amount": Decimal("60"),
                 "reversed_amount": Decimal("20"), "reversal_facts": [{"amount": 20}],
                 "value_source_public_id": UUID(int=11)}]

    @staticmethod
    def correlated_events(*args):
        return [{"id": 20, "public_id": UUID(int=20), "event_type_code": "payment_received"}]

    @staticmethod
    def correlated_journals(*args):
        return [{"id": 30, "public_id": UUID(int=30), "transaction_debits": Decimal("60"),
                 "transaction_credits": Decimal("60")}]


class TraceService(ObligationSettlementTraceService):
    repository = FakeRepository


def test_trace_reconstructs_balance_and_state():
    trace = TraceService.explain(object(), ObligationTraceQuery(35, OID))
    assert trace.balance["original_amount"] == Decimal("100")
    assert trace.balance["allocated_amount"] == Decimal("60")
    assert trace.balance["reversed_amount"] == Decimal("20")
    assert trace.balance["active_satisfaction"] == Decimal("40")
    assert trace.balance["outstanding_amount"] == Decimal("60")
    assert trace.balance["state_as_of"] == "partially_satisfied"


def test_trace_hides_internal_database_ids():
    trace = TraceService.explain(object(), ObligationTraceQuery(35, OID))
    assert "id" not in trace.obligation
    assert all("id" not in row for row in trace.allocations)
    assert all("id" not in row for row in trace.state_history)
    assert all("id" not in row for row in trace.correlated_financial_events)
    assert all("id" not in row for row in trace.correlated_journals)


def test_trace_integrity_passes_balanced_evidence():
    trace = TraceService.explain(object(), ObligationTraceQuery(35, OID))
    assert trace.integrity["status"] == "PASS"
    assert all(trace.integrity["checks"].values())


def test_explanation_labels_correlation_only():
    trace = TraceService.explain(object(), ObligationTraceQuery(35, OID))
    assert "correlation is evidence, not asserted causation" in trace.explanation["ledger_evidence"]
    assert "derived and read-only" in trace.explanation["authority"]


def test_wrong_tenant_is_not_found():
    with pytest.raises(ObligationTraceNotFound):
        TraceService.explain(object(), ObligationTraceQuery(36, OID))


def test_repository_is_select_only_and_uses_both_cutoffs():
    source = (ROOT / "core/domain/finance/obligation_trace_repository.py").read_text()
    assert "SELECT" in source
    assert not any(token in source.upper() for token in ("INSERT INTO", "UPDATE ", "DELETE FROM", "FOR UPDATE"))
    assert source.count(":as_of") >= 5
    assert source.count(":business_date") >= 5


def test_service_does_not_commit_or_flush():
    source = (ROOT / "core/domain/finance/obligation_trace_service.py").read_text()
    assert ".commit(" not in source and ".flush(" not in source and ".rollback(" not in source


def test_balance_equation_is_frozen():
    assert CONTRACT["balance_equation"] == "outstanding_amount = original_amount - allocated_amount + reversed_amount"


def test_no_migration_file_is_shipped():
    assert not list((ROOT / "alembic_neutral/versions").glob("m35_*.py"))


def test_forbidden_surface_is_explicit():
    forbidden = set(CONTRACT["forbidden"])
    assert {"database_mutation", "migration", "public_api_route", "causation_claim_from_correlation"} <= forbidden


def test_repository_uses_actual_journal_columns():
    source = (ROOT / "core/domain/finance/obligation_trace_repository.py").read_text()
    assert "transaction_debit_amount" in source and "transaction_credit_amount" in source
    assert "je.entry_kind" not in source and "je.occurred_at" not in source
