from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from core.domain.finance.operational_balance_contract import (
    ACTUAL_PROVENANCE,
    ANCHOR_PROVENANCE,
    CreateOperationalAccountCommand,
    OperationalBalanceQuery,
    OperationalBalanceValidationError,
    RecordActualBalanceCommand,
    RecordBalanceAnchorCommand,
)

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts/finance/v1/m60_operational_account_and_balance_authority.json"
UP = ROOT / "alembic_neutral/sql/m60_operational_balance_authority_up.sql"
DOWN = ROOT / "alembic_neutral/sql/m60_operational_balance_authority_down.sql"
MIGRATION = ROOT / "alembic_neutral/versions/m60_operational_balance_authority_016_treasury_accounts_and_balances.py"
REPOSITORY = ROOT / "core/domain/finance/operational_balance_repository.py"
BASE = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)


def account(**changes):
    values = dict(
        public_id=UUID(int=1), tenant_id=2, organization_unit_id=3,
        account_class="treasury", account_type="cash", code="front-drawer",
        display_name="Front Drawer", currency_code="xaf", aggregation_role="leaf",
        opened_at=BASE, correlation_id=UUID(int=9), source_component="m60.verifier",
        source_record_id="account", idempotency_scope="m60.account", idempotency_key="drawer",
        actor_service="m60.verifier", metadata={"location": "front"},
    )
    values.update(changes)
    return CreateOperationalAccountCommand(**values)


def anchor(**changes):
    values = dict(
        public_id=UUID(int=2), tenant_id=2, organization_unit_id=3,
        operational_account_public_id=UUID(int=1), anchor_balance="100", currency_code="XAF",
        anchor_at=BASE, provenance="opening_import", evidence_payload={"source": "approved-opening"},
        occurred_at=BASE, business_date=date(2026, 8, 10), calendar_policy_version=1,
        correlation_id=UUID(int=9), source_component="m60.verifier", source_record_id="anchor",
        idempotency_scope="m60.anchor", idempotency_key="anchor", actor_service="m60.verifier",
    )
    values.update(changes)
    return RecordBalanceAnchorCommand(**values)


def actual(**changes):
    values = dict(
        public_id=UUID(int=3), tenant_id=2, organization_unit_id=3,
        operational_account_public_id=UUID(int=1), actual_balance="128", currency_code="XAF",
        observed_at=BASE, provenance="operator_counted", evidence_payload={"count_sheet": "sha-bound"},
        occurred_at=BASE, business_date=date(2026, 8, 10), calendar_policy_version=1,
        correlation_id=UUID(int=9), source_component="m60.verifier", source_record_id="actual",
        idempotency_scope="m60.actual", idempotency_key="actual", actor_service="m60.verifier",
    )
    values.update(changes)
    return RecordActualBalanceCommand(**values)


def test_contract_identifies_consolidated_original_scope():
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert contract["scope"]["included_original_items"] == ["M6.0", "M6.1", "M6.2", "M6.3"]
    assert contract["canonical_target_revision"] == "m60_operational_balance_authority_016"


def test_projection_formulas_are_explicit_and_actual_absence_is_not_zero():
    projection = json.loads(CONTRACT.read_text(encoding="utf-8"))["projection"]
    assert projection["expected_balance"] == "anchor_balance + target_account_inflows - source_account_outflows"
    assert projection["variance"] == "actual_balance - expected_balance"
    assert projection["missing_actual"] == "variance_is_null_not_zero"


def test_migration_is_linear_from_m46():
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "m60_operational_balance_authority_016"' in source
    assert 'down_revision = "m46_provider_financials_015"' in source


@pytest.mark.parametrize("table", [
    "operational_account_authorities", "operational_account_balance_anchors",
    "operational_account_balance_observations",
])
def test_up_sql_creates_m60_authority_tables(table):
    assert f"CREATE TABLE public.{table}" in UP.read_text(encoding="utf-8")


def test_balance_facts_are_append_only_and_evidenced():
    source = UP.read_text(encoding="utf-8")
    assert "trg_operational_balance_anchor_immutable" in source
    assert "trg_operational_balance_observation_immutable" in source
    assert "evidence_hash ~ '^[0-9a-f]{64}$'" in source
    assert "evidence_payload <> '{}'::jsonb" in source


def test_single_anchor_and_observation_cutoff_indexes_are_enforced():
    source = UP.read_text(encoding="utf-8")
    assert "uq_operational_account_balance_anchors_account UNIQUE (tenant_id, operational_account_id)" in source
    assert "observed_at DESC, id DESC" in source


def test_account_identity_and_parent_hierarchy_are_protected():
    source = UP.read_text(encoding="utf-8")
    assert "xbos_protect_operational_account_identity" in source
    assert "parent_row.organization_unit_id<>NEW.organization_unit_id" in source
    assert "parent_row.currency_code<>NEW.currency_code" in source
    assert "parent_row.aggregation_role<>'parent_aggregate'" in source


def test_balance_facts_require_leaf_scope_currency_and_lifetime():
    source = UP.read_text(encoding="utf-8")
    assert "account_row.aggregation_role<>'leaf'" in source
    assert "account_row.organization_unit_id<>NEW.organization_unit_id" in source
    assert "account_row.currency_code<>NEW.currency_code" in source
    assert "fact_at<account_row.opened_at" in source


def test_balance_fact_trigger_uses_only_table_valid_timestamp_fields():
    source = UP.read_text(encoding="utf-8")
    assert "IF TG_TABLE_NAME='operational_account_balance_anchors' THEN\n        fact_at := NEW.anchor_at;" in source
    assert "ELSIF TG_TABLE_NAME='operational_account_balance_observations' THEN\n        fact_at := NEW.observed_at;" in source
    assert "unexpected operational balance fact trigger table" in source
    assert "fact_at := CASE" not in source


def test_down_sql_removes_only_m60_objects_and_triggers():
    source = DOWN.read_text(encoding="utf-8")
    assert "DROP TABLE IF EXISTS public.operational_account_balance_observations" in source
    assert "DROP TABLE IF EXISTS public.operational_account_balance_anchors" in source
    assert "DROP TABLE IF EXISTS public.operational_account_authorities" in source
    assert "DROP TABLE IF EXISTS public.operational_financial_accounts" not in source
    assert "DROP TABLE IF EXISTS public.financial_events" not in source


def test_account_command_normalizes_identity_and_currency():
    command = account(code=" Drawer.One ", currency_code="xaf", account_type="CASH")
    assert command.code == "drawer.one"
    assert command.currency_code == "XAF"
    assert command.account_type == "cash"


@pytest.mark.parametrize("field,value,code", [
    ("tenant_id", 0, "invalid_scope"),
    ("account_class", "wallet", "invalid_account_kind"),
    ("account_type", "crypto", "invalid_account_kind"),
    ("aggregation_role", "both", "invalid_aggregation_role"),
    ("code", "UPPER CASE", "invalid_account_identity"),
    ("currency_code", "1", "invalid_currency"),
])
def test_invalid_account_contract_rejected(field, value, code):
    with pytest.raises(OperationalBalanceValidationError) as raised:
        account(**{field: value})
    assert raised.value.code == code


def test_account_cannot_parent_itself():
    with pytest.raises(OperationalBalanceValidationError) as raised:
        account(parent_account_public_id=UUID(int=1))
    assert raised.value.code == "invalid_parent"


def test_account_requires_timezone_and_actor():
    with pytest.raises(OperationalBalanceValidationError) as raised:
        account(opened_at=BASE.replace(tzinfo=None))
    assert raised.value.code == "timezone_required"
    with pytest.raises(OperationalBalanceValidationError) as raised:
        account(actor_service=None)
    assert raised.value.code == "actor_required"


def test_account_fingerprint_is_deterministic_and_content_sensitive():
    first = account()
    assert first.request_fingerprint == account().request_fingerprint
    assert first.request_fingerprint != account(display_name="Back Drawer").request_fingerprint
    assert len(first.request_fingerprint) == 64


@pytest.mark.parametrize("provenance", sorted(ANCHOR_PROVENANCE))
def test_anchor_provenance_is_accepted(provenance):
    assert anchor(provenance=provenance).provenance == provenance


@pytest.mark.parametrize("provenance", sorted(ACTUAL_PROVENANCE))
def test_actual_provenance_is_accepted(provenance):
    assert actual(provenance=provenance).provenance == provenance


def test_anchor_and_actual_provenance_are_not_interchangeable():
    with pytest.raises(OperationalBalanceValidationError) as raised:
        anchor(provenance="operator_counted")
    assert raised.value.code == "invalid_provenance"
    with pytest.raises(OperationalBalanceValidationError) as raised:
        actual(provenance="opening_import")
    assert raised.value.code == "invalid_provenance"


@pytest.mark.parametrize("factory", [anchor, actual])
def test_balance_fact_requires_evidence_timezone_currency_and_actor(factory):
    for changes, code in (
        ({"evidence_payload": {}}, "evidence_required"),
        ({"occurred_at": BASE.replace(tzinfo=None)}, "timezone_required"),
        ({"currency_code": "bad currency"}, "invalid_currency"),
        ({"actor_service": None}, "actor_required"),
    ):
        with pytest.raises(OperationalBalanceValidationError) as raised:
            factory(**changes)
        assert raised.value.code == code


@pytest.mark.parametrize("factory,field", [(anchor, "anchor_balance"), (actual, "actual_balance")])
def test_signed_balances_are_supported_but_storage_overflow_is_rejected(factory, field):
    assert getattr(factory(**{field: "-12.5"}), field) == Decimal("-12.50000000")
    with pytest.raises(OperationalBalanceValidationError) as raised:
        factory(**{field: "10000000000000000"})
    assert raised.value.code == "invalid_amount"


def test_evidence_hash_and_request_fingerprint_are_lowercase_sha256():
    command = actual()
    assert len(command.evidence_hash) == 64
    assert command.evidence_hash == command.evidence_hash.lower()
    assert len(command.request_fingerprint) == 64


def test_query_is_tenant_org_scoped_and_timezone_aware():
    query = OperationalBalanceQuery(2, 3, UUID(int=1), BASE)
    assert query.tenant_id == 2 and query.organization_unit_id == 3
    with pytest.raises(OperationalBalanceValidationError) as raised:
        OperationalBalanceQuery(2, 3, UUID(int=1), BASE.replace(tzinfo=None))
    assert raised.value.code == "timezone_required"


def test_repository_projection_uses_anchor_cutoff_event_direction_and_latest_actual():
    source = REPOSITORY.read_text(encoding="utf-8")
    assert "target_operational_account_id=:account THEN amount" in source
    assert "source_operational_account_id=:account THEN amount" in source
    assert "occurred_at>anchor.anchor_at AND occurred_at<=:as_of" in source
    assert "observed_at<=:as_of" in source
    assert "actual.actual_balance-(anchor.anchor_balance+movement.inflows-movement.outflows)" in source


def test_projection_never_uses_journal_or_provider_rows_as_competing_movement_authority():
    source = REPOSITORY.read_text(encoding="utf-8")
    assert "FROM public.financial_events,anchor" in source
    assert "journal_entries" not in source
    assert "payment_settlements" not in source
    assert "provider_settlement_components" not in source
