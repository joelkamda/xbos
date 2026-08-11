from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from core.domain.finance.operational_balance_repository import OperationalAccountRecord
from core.domain.finance.operational_transfer_contract import (
    OperationalTransferValidationError,
    ReconciliationSeriesQuery,
    RecordOperationalTransferCommand,
    ReverseOperationalTransferCommand,
    TRANSFER_PROVENANCE,
)
from core.domain.finance.operational_transfer_engine import TransactionalOperationalTransferEngine
from core.domain.finance.operational_transfer_repository import OriginalTransferRecord

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts/finance/v1/m61_operational_transfers_and_reconciliation_series.json"
UP = ROOT / "alembic_neutral/sql/m61_operational_transfers_up.sql"
DOWN = ROOT / "alembic_neutral/sql/m61_operational_transfers_down.sql"
MIGRATION = ROOT / "alembic_neutral/versions/m61_transfers_reconciliation_017_operational_value_series.py"
REPOSITORY = ROOT / "core/domain/finance/operational_transfer_repository.py"
SERIES = ROOT / "core/domain/finance/reconciliation_series_service.py"
VERIFIER = ROOT / "scripts/verify_m61_operational_transfers.py"
BASE = datetime(2026, 8, 10, 12, tzinfo=timezone.utc)
SOURCE = UUID("61000000-0000-0000-0000-000000000001")
DESTINATION = UUID("61000000-0000-0000-0000-000000000002")


def transfer(**changes):
    values = dict(
        public_id=UUID("61000000-0000-0000-0001-000000000001"), tenant_id=2,
        organization_unit_id=3, source_operational_account_public_id=SOURCE,
        destination_operational_account_public_id=DESTINATION, amount="25", currency_code="xaf",
        occurred_at=BASE, value_at=BASE + timedelta(minutes=1), business_date=date(2026, 8, 10),
        calendar_policy_version=1, provenance="operator_authorized", transfer_purpose="treasury_sweep",
        evidence_payload={"authorization": "approved"}, source_record_id=41,
        idempotency_scope="m61.transfer", idempotency_key="sweep-1",
        correlation_id=UUID("61000000-0000-0000-0000-000000000099"), actor_service="m61.verifier",
    )
    values.update(changes)
    return RecordOperationalTransferCommand(**values)


def reversal(**changes):
    values = dict(
        public_id=UUID("61000000-0000-0000-0002-000000000001"), tenant_id=2,
        organization_unit_id=3, original_transfer_public_id=UUID("61000000-0000-0000-0001-000000000001"),
        amount="10", currency_code="XAF", occurred_at=BASE + timedelta(minutes=2),
        value_at=BASE + timedelta(minutes=2), business_date=date(2026, 8, 10),
        calendar_policy_version=1, reversal_reason="authorization_voided",
        evidence_payload={"approval": "reversal"}, source_record_id=42,
        idempotency_scope="m61.reversal", idempotency_key="reverse-1",
        correlation_id=UUID("61000000-0000-0000-0000-000000000099"), actor_service="m61.verifier",
    )
    values.update(changes)
    return ReverseOperationalTransferCommand(**values)


def account(account_id, public_id):
    return OperationalAccountRecord(
        account_id, public_id, 2, 3, None, "treasury", "cash", f"account-{account_id}",
        f"Account {account_id}", "XAF", "leaf", True, True, BASE - timedelta(days=1), None,
    )


class FakeRepository:
    @staticmethod
    def lock_transfer_by_idempotency(session, **kwargs): return None

    @staticmethod
    def lock_accounts(session, **kwargs):
        return account(11, SOURCE), account(12, DESTINATION)

    @staticmethod
    def lock_original_transfer(session, **kwargs):
        return OriginalTransferRecord(51, kwargs["public_id"], 2, 3, 11, 12, Decimal("25"), "XAF", BASE)

    @staticmethod
    def account_by_id(session, **kwargs):
        return account(kwargs["account_id"], SOURCE if kwargs["account_id"] == 11 else DESTINATION)


class FakePosting:
    command = None

    @classmethod
    def emit_and_post(cls, session, command):
        cls.command = command
        return command


class FakeEngine(TransactionalOperationalTransferEngine):
    repository = FakeRepository
    posting_engine = FakePosting


class FakeTransaction:
    def __enter__(self): return self
    def __exit__(self, *args): return False


class FakeSession:
    def begin_nested(self): return FakeTransaction()


def test_contract_freezes_non_pnl_transfer_authority():
    data = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert data["transfer_authority"]["profit_and_loss_effect"] == "none"
    assert data["transfer_authority"]["atomicity"].startswith("one immutable event")


def test_scope_defers_windows_and_close():
    deferred = json.loads(CONTRACT.read_text(encoding="utf-8"))["deferred_to_m62_plus"]
    assert "reconciliation_windows" in deferred and "formal_close_or_reopen" in deferred


def test_migration_is_linear_and_uses_raw_cursor():
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "m61_transfers_reconciliation_017"' in source
    assert 'down_revision = "m60_operational_balance_authority_016"' in source
    assert "op.get_bind().connection.cursor()" in source and "exec_driver_sql" not in source


def test_sql_installs_fail_closed_transfer_trigger_and_series_view():
    source = UP.read_text(encoding="utf-8")
    assert "tr_financial_events_m61_transfer_validate" in source
    assert "CREATE VIEW public.operational_account_reconciliation_series" in source
    assert "unexpected" not in source


def test_sql_enforces_bilateral_scope_currency_and_evidence():
    source = UP.read_text(encoding="utf-8")
    for token in ("source_operational_account_id", "target_operational_account_id", "organization_unit_id", "currency_code", "evidence_payload", "value_at"):
        assert token in source


def test_down_removes_only_m61_objects():
    source = DOWN.read_text(encoding="utf-8")
    assert "DROP VIEW IF EXISTS public.operational_account_reconciliation_series" in source
    assert "DROP TRIGGER IF EXISTS tr_financial_events_m61_transfer_validate" in source
    assert "DROP TABLE" not in source


def test_series_is_deterministic_and_tenant_scoped():
    source = REPOSITORY.read_text(encoding="utf-8")
    assert "tenant_id=:tenant AND organization_unit_id=:org AND operational_account_id=:account" in source
    assert "ORDER BY fact_at,sort_rank,recorded_at,fact_public_id,direction" in source
    assert "ORDER BY a.id\n            FOR UPDATE OF a" in source


def test_series_service_is_read_only():
    source = SERIES.read_text(encoding="utf-8")
    assert all(token not in source for token in ("INSERT INTO", "UPDATE ", "DELETE FROM"))


def test_existing_catalog_transfer_profile_is_asset_to_asset():
    catalog = json.loads((ROOT / "contracts/finance/v1/financial_event_catalog.json").read_text(encoding="utf-8"))
    event = next(item for item in catalog["event_types"] if item["event_type_code"] == "VALUE_TRANSFERRED")
    profile = event["posting_profiles"][0]
    assert event["reconciliation_policy"]["effect"] == "movement"
    assert profile["debit_account_roles"] == ["target_operational_asset"]
    assert profile["credit_account_roles"] == ["source_operational_asset"]


def test_posting_bindings_are_directionally_exact():
    source = (ROOT / "core/domain/finance/posting_repository.py").read_text(encoding="utf-8")
    assert '"source_operational_asset": event.source_operational_account_id' in source
    assert '"target_operational_asset": event.target_operational_account_id' in source
    assert "operational_link_direction_mismatch" in source


def test_verifier_uses_canonical_event_to_journal_link_authority():
    source = VERIFIER.read_text(encoding="utf-8")
    assert "JOIN journal_entry_event_links link" in source
    assert "link.financial_event_id=fe.id" in source
    assert "link.allocation_role='primary_event_posting'" in source
    assert "je.financial_event_id" not in source
    assert "la.account_type<>'asset'" in source
    assert "source_operational_asset" in source and "target_operational_asset" in source


@pytest.mark.parametrize("provenance", sorted(TRANSFER_PROVENANCE))
def test_approved_transfer_provenance(provenance):
    assert transfer(provenance=provenance).provenance == provenance


@pytest.mark.parametrize("changes,code", [
    ({"amount": "0"}, "invalid_amount"),
    ({"amount": "-1"}, "invalid_amount"),
    ({"currency_code": "bad currency"}, "invalid_currency"),
    ({"tenant_id": 0}, "invalid_scope"),
    ({"evidence_payload": {}}, "evidence_required"),
    ({"actor_service": None}, "actor_required"),
    ({"source_record_id": 0}, "invalid_source_record"),
    ({"provenance": "guessed"}, "invalid_provenance"),
])
def test_invalid_transfer_rejected(changes, code):
    with pytest.raises(OperationalTransferValidationError) as raised:
        transfer(**changes)
    assert raised.value.code == code


def test_same_account_rejected():
    with pytest.raises(OperationalTransferValidationError) as raised:
        transfer(destination_operational_account_public_id=SOURCE)
    assert raised.value.code == "accounts_must_differ"


def test_transfer_fingerprint_is_deterministic_and_content_sensitive():
    assert transfer().request_fingerprint == transfer().request_fingerprint
    assert transfer().request_fingerprint != transfer(amount="26").request_fingerprint


def test_evidence_hash_is_lowercase_sha256():
    assert len(transfer().evidence_hash) == 64 and transfer().evidence_hash.islower()


def test_transfer_engine_builds_one_bilateral_non_pnl_event():
    event = FakeEngine.record(FakeSession(), transfer())
    assert event.event_type_code == "VALUE_TRANSFERRED" and event.economic_role == "transfer"
    assert (event.source_operational_account_id, event.target_operational_account_id) == (11, 12)
    assert event.posting_context["posting_profile_code"] == "operational_value_transfer"
    assert event.metadata["transfer"]["evidence_payload"] == {"authorization": "approved"}


@pytest.mark.parametrize("source_changes,code", [
    ({"currency_code": "USD"}, "account_currency_mismatch"),
    ({"organization_unit_id": 9}, "account_organization_mismatch"),
    ({"aggregation_role": "parent_aggregate"}, "account_not_eligible"),
    ({"active": False}, "account_not_eligible"),
])
def test_engine_rejects_ineligible_source(source_changes, code):
    selected = account(11, SOURCE)
    selected = replace(selected, **source_changes)
    class Repository(FakeRepository):
        @staticmethod
        def lock_accounts(session, **kwargs): return selected, account(12, DESTINATION)
    class Engine(FakeEngine): repository = Repository
    with pytest.raises(OperationalTransferValidationError) as raised:
        Engine.record(FakeSession(), transfer())
    assert raised.value.code == code


def test_reversal_is_append_only_inverse_event():
    event = FakeEngine.reverse(FakeSession(), reversal())
    assert event.event_type_code == "FINANCIAL_FACT_REVERSED" and event.original_event_id == 51
    assert (event.source_operational_account_id, event.target_operational_account_id) == (12, 11)
    assert event.posting_context["posting_profile_code"] == "inverse_original_fact"


def test_reversal_fingerprint_changes_with_amount():
    assert reversal().request_fingerprint != reversal(amount="11").request_fingerprint


def test_series_query_normalizes_and_rejects_reverse_range():
    query = ReconciliationSeriesQuery(2, 3, SOURCE, BASE + timedelta(hours=1), BASE)
    assert query.operational_account_public_id == SOURCE
    with pytest.raises(OperationalTransferValidationError) as raised:
        ReconciliationSeriesQuery(2, 3, SOURCE, BASE, BASE + timedelta(hours=1))
    assert raised.value.code == "invalid_series_range"


def test_view_keeps_original_and_reversal_visible():
    source = UP.read_text(encoding="utf-8")
    assert "'transfer_reversal'" in source
    assert "original.public_id" in source
    assert "UNION ALL" in source


def test_expected_balance_remains_m60_event_projection():
    source = (ROOT / "core/domain/finance/operational_balance_repository.py").read_text(encoding="utf-8")
    assert "target_operational_account_id=:account THEN amount" in source
    assert "source_operational_account_id=:account THEN amount" in source


def test_persistent_verifier_exists():
    assert (ROOT / "scripts/verify_m61_operational_transfers.py").is_file()
