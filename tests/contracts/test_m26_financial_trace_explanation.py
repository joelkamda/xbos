import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest


pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "contracts" / "finance" / "v1" / "m26_financial_trace_and_explanation.json"
CONTRACT_CODE_PATH = ROOT / "core" / "domain" / "finance" / "trace_contract.py"
REPOSITORY_PATH = ROOT / "core" / "domain" / "finance" / "trace_repository.py"
SERVICE_PATH = ROOT / "core" / "domain" / "finance" / "trace_service.py"
VERIFIER_PATH = ROOT / "scripts" / "verify_m26_financial_trace_explanation.py"
ALEMBIC_INI = ROOT / "alembic.ini"


@pytest.fixture(scope="module")
def contract():
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_contract_identity(contract):
    assert contract["contract_code"] == "XBOS_M26_FINANCIAL_TRACE_EXPLANATION"
    assert contract["contract_version"] == 1
    assert contract["package_revision"] == 1
    assert contract["status"] == "approved_implementation_candidate"


def test_contract_is_anchored_to_committed_m25(contract):
    assert contract["parent_checkpoint"] == {
        "commit": "d57bd05",
        "migration_revision": "m25_financial_dimensions_007",
    }


def test_m26_is_schema_neutral(contract):
    assert contract["schema_change"] is False
    assert contract["target_revision"] == "m25_financial_dimensions_007"
    assert not list((ROOT / "alembic_neutral" / "versions").glob("m26_*.py"))


def test_query_requires_tenant_and_public_event_identity(contract):
    assert contract["query_identity"]["required"] == ["tenant_id", "event_public_id"]
    assert contract["query_identity"]["event_identity"] == "public_uuid"


@pytest.mark.parametrize("tenant", [0, -1, "", None, "not-an-int"])
def test_query_rejects_invalid_tenant_scope(tenant):
    from core.domain.finance.trace_contract import (
        FinancialEventTraceQuery,
        FinancialTraceValidationError,
    )

    with pytest.raises(FinancialTraceValidationError) as exc:
        FinancialEventTraceQuery(tenant, UUID(int=1))
    assert exc.value.code == "invalid_tenant_scope"


@pytest.mark.parametrize("event_id", ["", "nope", None, 5])
def test_query_rejects_invalid_event_identity(event_id):
    from core.domain.finance.trace_contract import (
        FinancialEventTraceQuery,
        FinancialTraceValidationError,
    )

    with pytest.raises(FinancialTraceValidationError) as exc:
        FinancialEventTraceQuery(1, event_id)
    assert exc.value.code == "invalid_event_identity"


def test_query_normalizes_identifiers():
    from core.domain.finance.trace_contract import FinancialEventTraceQuery

    query = FinancialEventTraceQuery("2", "00000000-0000-0000-0000-000000000001")
    assert query.tenant_id == 2
    assert query.event_public_id == UUID(int=1)


def test_repository_is_select_only():
    source = REPOSITORY_PATH.read_text(encoding="utf-8").upper()
    for mutation in ("INSERT INTO", "UPDATE PUBLIC.", "DELETE FROM", "FOR UPDATE", "FOR SHARE"):
        assert mutation not in source


def test_repository_has_no_commit_or_flush():
    source = REPOSITORY_PATH.read_text(encoding="utf-8")
    assert ".commit(" not in source
    assert ".flush(" not in source
    assert "begin_nested" not in source


def test_every_repository_query_is_tenant_scoped():
    source = REPOSITORY_PATH.read_text(encoding="utf-8")
    assert source.count(":tenant_id") >= 11
    assert source.count('"tenant_id":') >= 8


def test_primary_posting_is_explicitly_selected():
    source = REPOSITORY_PATH.read_text(encoding="utf-8")
    assert "allocation_role = 'primary_event_posting'" in source
    assert "LIMIT 2" in source
    assert "ambiguous_primary_entries" in source


def test_posting_trace_uses_persisted_accounts_roles_and_dimensions():
    source = REPOSITORY_PATH.read_text(encoding="utf-8")
    for field in (
        "ledger_account_public_id",
        "account_code",
        "account_name",
        "account_role",
        "dimension_snapshot",
    ):
        assert field in source


def test_lineage_is_recursive_and_tenant_scoped():
    source = REPOSITORY_PATH.read_text(encoding="utf-8")
    assert "WITH RECURSIVE ancestors" in source
    assert "descendants AS" in source
    assert "parent.tenant_id = :tenant_id" in source
    assert "child.tenant_id = :tenant_id" in source


def test_service_does_not_import_http_framework():
    source = SERVICE_PATH.read_text(encoding="utf-8").lower()
    assert "fastapi" not in source
    assert "router" not in source


class FakeRepository:
    event_id = UUID("11111111-1111-1111-1111-111111111111")

    @classmethod
    def load_event(cls, session, query):
        if query.event_public_id != cls.event_id:
            return None
        return {
            "id": 8,
            "public_id": cls.event_id,
            "tenant_id": query.tenant_id,
            "organization_unit_id": 4,
            "organization_unit_public_id": UUID("22222222-2222-2222-2222-222222222222"),
            "organization_unit_code": "ENTITY",
            "organization_unit_name": "Example Entity",
            "organization_unit_type": "legal_entity",
            "event_type_code": "EXPENSE_RECOGNIZED",
            "event_version": 1,
            "amount": Decimal("100.00"),
            "currency_code": "XAF",
            "economic_role": "recognition",
            "source_operational_account_id": None,
            "target_operational_account_id": None,
            "source_record_id": 5,
            "original_event_id": None,
            "original_event_public_id": None,
            "occurred_at": datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc),
            "recorded_at": datetime(2026, 8, 8, 10, 1, tzinfo=timezone.utc),
            "business_date": date(2026, 8, 8),
            "calendar_policy_version": 1,
            "actor_user_id": None,
            "actor_service": "test",
            "idempotency_scope": "finance",
            "idempotency_key": "expense-1",
            "correlation_id": UUID("33333333-3333-3333-3333-333333333333"),
            "causation_id": None,
            "classification_snapshot": {},
            "posting_context": {"posting_profile_code": "expense_accrual"},
            "evidence_hash": None,
            "metadata": {},
            "event_display_name": "Expense recognized",
            "event_definition": "Recognize an expense.",
            "reconciliation_effect": "commercial",
            "posting_eligible": True,
            "catalog_definition_hash": "a" * 64,
        }

    @staticmethod
    def load_source(session, **kwargs):
        return {
            "public_id": UUID("44444444-4444-4444-4444-444444444444"),
            "tenant_id": kwargs["tenant_id"],
            "source_component": "example",
            "aggregate_type": "expense",
            "aggregate_external_id": "EXP-1",
            "aggregate_version": "1",
            "registered_at": datetime(2026, 8, 8, 10, 0, tzinfo=timezone.utc),
            "retired_at": None,
            "metadata": {},
        }

    @staticmethod
    def load_idempotency(session, **kwargs):
        return {
            "tenant_id": kwargs["tenant_id"],
            "scope": kwargs["scope"],
            "idempotency_key": kwargs["idempotency_key"],
            "request_fingerprint": "b" * 64,
            "processing_state": "completed",
            "response_code": 201,
            "response_snapshot": {},
            "completed_at": datetime(2026, 8, 8, 10, 1, tzinfo=timezone.utc),
        }

    @staticmethod
    def load_outbox(session, **kwargs):
        return {
            "public_id": UUID("55555555-5555-5555-5555-555555555555"),
            "tenant_id": kwargs["tenant_id"],
            "source_event_public_id": kwargs["event_public_id"],
            "topic": "finance.financial-events.v1",
            "message_key": str(kwargs["event_public_id"]),
            "event_name": "EXPENSE_RECOGNIZED",
            "event_version": 1,
            "payload_hash": "c" * 64,
            "delivery_state": "pending",
            "delivery_attempts": 0,
        }

    @staticmethod
    def load_posting(session, **kwargs):
        return {
            "public_id": UUID("66666666-6666-6666-6666-666666666666"),
            "tenant_id": kwargs["tenant_id"],
            "posting_profile_code": "expense_accrual",
            "entry_state": "posted",
            "transaction_currency_code": "XAF",
            "base_currency_code": "XAF",
            "lines": [
                {
                    "line_number": 1,
                    "tenant_id": kwargs["tenant_id"],
                    "account_role": "classified_expense",
                    "transaction_debit_amount": Decimal("100"),
                    "transaction_credit_amount": Decimal("0"),
                    "base_debit_amount": Decimal("100"),
                    "base_credit_amount": Decimal("0"),
                    "dimension_snapshot": {"financial_dimensions": {"project": {"value_code": "p1"}}},
                },
                {
                    "line_number": 2,
                    "tenant_id": kwargs["tenant_id"],
                    "account_role": "trade_or_accrued_payable",
                    "transaction_debit_amount": Decimal("0"),
                    "transaction_credit_amount": Decimal("100"),
                    "base_debit_amount": Decimal("0"),
                    "base_credit_amount": Decimal("100"),
                    "dimension_snapshot": {"financial_dimensions": {}},
                },
            ],
        }

    @classmethod
    def load_correction_lineage(cls, session, **kwargs):
        return ({"public_id": cls.event_id, "relationship": "selected", "depth": 0},)

    @staticmethod
    def load_correlation_peers(session, **kwargs):
        return ()


def _service():
    from core.domain.finance.trace_service import CanonicalFinancialTraceService

    class Service(CanonicalFinancialTraceService):
        repository = FakeRepository

    return Service


def _query(tenant=7):
    from core.domain.finance.trace_contract import FinancialEventTraceQuery

    return FinancialEventTraceQuery(tenant, FakeRepository.event_id)


def test_service_builds_complete_passing_trace():
    trace = _service().explain(object(), _query())
    assert trace.integrity["status"] == "PASS"
    assert trace.integrity["transaction_debits"] == Decimal("100")
    assert trace.integrity["transaction_credits"] == Decimal("100")
    assert trace.posting["lines"][0]["dimension_snapshot"]["financial_dimensions"]


def test_trace_is_deterministic():
    first = _service().explain(object(), _query())
    second = _service().explain(object(), _query())
    assert first.envelope() == second.envelope()
    assert first.fingerprint == second.fingerprint
    assert len(first.fingerprint) == 64


def test_trace_has_no_generated_at_field():
    envelope = _service().explain(object(), _query()).envelope()
    assert "generated_at" not in json.dumps(envelope)


def test_trace_uses_public_ids_not_internal_event_ids():
    envelope = _service().explain(object(), _query()).envelope()
    assert "source_record_id" not in envelope["event"]
    assert "original_event_id" not in envelope["event"]
    assert envelope["event"]["public_id"] == str(FakeRepository.event_id)


def test_trace_decimal_and_timestamp_serialization_is_canonical():
    envelope = _service().explain(object(), _query()).envelope()
    assert envelope["event"]["amount"] == "100"
    assert envelope["event"]["occurred_at"] == "2026-08-08T10:00:00Z"


def test_missing_event_is_tenant_safe_not_found():
    from core.domain.finance.trace_contract import FinancialEventTraceQuery, FinancialTraceNotFound

    with pytest.raises(FinancialTraceNotFound) as exc:
        _service().explain(object(), FinancialEventTraceQuery(7, UUID(int=99)))
    assert exc.value.code == "financial_event_not_found"
    assert "another tenant" not in str(exc.value).lower()


def test_cross_tenant_repository_result_is_rejected():
    from core.domain.finance.trace_contract import FinancialTraceIntegrityError

    class CrossTenant(FakeRepository):
        @classmethod
        def load_event(cls, session, query):
            result = dict(super().load_event(session, query))
            result["tenant_id"] = query.tenant_id + 1
            return result

    service = _service()
    service.repository = CrossTenant
    with pytest.raises(FinancialTraceIntegrityError) as exc:
        service.explain(object(), _query())
    assert exc.value.code == "tenant_scope_violation"


def test_missing_source_is_integrity_error():
    from core.domain.finance.trace_contract import FinancialTraceIntegrityError

    class MissingSource(FakeRepository):
        @staticmethod
        def load_source(session, **kwargs):
            return None

    service = _service()
    service.repository = MissingSource
    with pytest.raises(FinancialTraceIntegrityError) as exc:
        service.explain(object(), _query())
    assert exc.value.code == "source_record_missing"


@pytest.mark.parametrize(
    "override,failed_check",
    [
        ({"load_idempotency": lambda *args, **kwargs: None}, "idempotency_completed"),
        ({"load_outbox": lambda *args, **kwargs: None}, "outbox_present"),
        ({"load_posting": lambda *args, **kwargs: None}, "posting_presence_matches_catalog"),
    ],
)
def test_missing_authoritative_link_fails_integrity(override, failed_check):
    repository = type("Incomplete", (FakeRepository,), override)
    service = _service()
    service.repository = repository
    trace = service.explain(object(), _query())
    assert trace.integrity["status"] == "FAIL"
    assert trace.integrity["checks"][failed_check] is False


def test_unbalanced_lines_fail_both_balance_checks():
    class Unbalanced(FakeRepository):
        @staticmethod
        def load_posting(session, **kwargs):
            posting = FakeRepository.load_posting(session, **kwargs)
            posting["lines"][1]["transaction_credit_amount"] = Decimal("90")
            posting["lines"][1]["base_credit_amount"] = Decimal("90")
            return posting

    service = _service()
    service.repository = Unbalanced
    trace = service.explain(object(), _query())
    assert trace.integrity["status"] == "FAIL"
    assert trace.integrity["checks"]["transaction_currency_balanced"] is False
    assert trace.integrity["checks"]["base_currency_balanced"] is False


def test_explanation_states_derived_authority_boundary():
    trace = _service().explain(object(), _query())
    assert "derived and read-only" in trace.explanation["authority"]


def test_verifier_uses_exact_disposable_database():
    source = VERIFIER_PATH.read_text(encoding="utf-8")
    assert 'TEST_DATABASE_NAME = "xbos_track_b_m26_trace_test"' in source
    assert "--confirm-database-name" in source


def test_verifier_does_not_write_development_financial_truth():
    source = VERIFIER_PATH.read_text(encoding="utf-8")
    assert "development_counts" in source
    assert '"financial_events",' in source
    assert '"outbox_messages",' in source
    assert "_assert_empty_financial_truth" in source
    assert "INSERT INTO" not in source


def test_main_alembic_authority_remains_neutral_lineage():
    source = ALEMBIC_INI.read_text(encoding="utf-8")
    assert "script_location = %(here)s/alembic_neutral" in source
