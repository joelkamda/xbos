"""Executable contract checks for M4.6 provider financials."""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts" / "finance" / "v1" / "m46_provider_fees_reserves_and_adjustments.json"
UP = ROOT / "alembic_neutral" / "sql" / "m46_provider_financials_up.sql"
DOWN = ROOT / "alembic_neutral" / "sql" / "m46_provider_financials_down.sql"
MIGRATION = ROOT / "alembic_neutral" / "versions" / "m46_provider_financials_015_fees_reserves_and_adjustments.py"
ENGINE = ROOT / "core" / "domain" / "finance" / "provider_financial_engine.py"
REPOSITORY = ROOT / "core" / "domain" / "finance" / "provider_financial_repository.py"
VERIFIER = ROOT / "scripts" / "verify_m46_provider_financials.py"
BASE = datetime(2026, 8, 10, 9, tzinfo=timezone.utc)


def _command(**changes):
    from core.domain.finance.provider_financial_contract import CreateProviderSettlementComponentCommand
    values = dict(
        public_id=UUID(int=1), tenant_id=1, organization_unit_id=2,
        payment_settlement_public_id=UUID(int=2), provider_account_public_id=UUID(int=3),
        component_type="provider_fee", classification_code="network_fee", amount="5", currency_code="XAF",
        provider_event_reference="provider-event-1", value_date=date(2026, 8, 10),
        evidence_payload={"provider": "tranzak"}, occurred_at=BASE, business_date=date(2026, 8, 10),
        calendar_policy_version=1, correlation_id=UUID(int=4), actor_service="tests",
        source_component="tests", source_record_id="component-1",
        idempotency_scope="tests.m46", idempotency_key="one",
    )
    values.update(changes)
    return CreateProviderSettlementComponentCommand(**values)


def test_contract_declares_full_m46_scope():
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert contract["contract"] == "XBOS_M46_PROVIDER_FEES_RESERVES_AND_ADJUSTMENTS"
    assert set(contract["component_types"]) == {"provider_fee", "reserve_hold", "reserve_release", "chargeback_loss"}
    assert contract["gross_settlement_truth"]["rewrite_allowed"] is False
    assert contract["net_position"]["formula"] == "gross - fees - active_reserves - chargeback_losses"


def test_migration_chain_is_linear_and_intentional():
    source = MIGRATION.read_text(encoding="utf-8")
    assert 'revision = "m46_provider_financials_015"' in source
    assert 'down_revision = "m44_payment_patterns_014"' in source
    assert "m46_provider_financials_up.sql" in source
    assert "m46_provider_financials_down.sql" in source


@pytest.mark.parametrize("fragment", [
    "CREATE TABLE public.provider_settlement_components",
    "provider_fee", "reserve_hold", "reserve_release", "chargeback_loss",
    "original_component_id", "provider_event_reference", "request_fingerprint",
    "trg_provider_settlement_component_validate", "trg_provider_settlement_component_immutable",
    "FOR UPDATE OF s", "reserve release exceeds original hold capacity",
    "provider components exceed gross settlement capacity",
])
def test_up_sql_installs_required_authority(fragment):
    assert fragment in UP.read_text(encoding="utf-8")


def test_sql_authority_is_governed_and_append_only():
    source = UP.read_text(encoding="utf-8")
    assert "current_setting('xbos.m46_component_authorized',true)" in source
    assert "BEFORE UPDATE OR DELETE" in source
    assert "append-only" in source
    assert "%%ROWTYPE" not in source


def test_down_sql_removes_only_m46_objects():
    source = DOWN.read_text(encoding="utf-8")
    assert "DROP TABLE IF EXISTS public.provider_settlement_components" in source
    assert "DROP FUNCTION IF EXISTS public.xbos_validate_provider_settlement_component" in source
    assert "payment_settlements" not in source


def test_valid_fee_is_canonical_and_fingerprinted():
    command = _command()
    assert command.amount.as_tuple().exponent == -8
    assert command.canonical_payload()["amount"] == "5"
    assert len(command.request_fingerprint) == 64
    assert len(command.evidence_hash) == 64


def test_reserve_release_requires_original_hold():
    from core.domain.finance.provider_financial_contract import ProviderFinancialValidationError
    with pytest.raises(ProviderFinancialValidationError) as exc:
        _command(component_type="reserve_release", classification_code="reserve_release")
    assert exc.value.code == "original_hold_required"


def test_only_release_may_link_original_component():
    from core.domain.finance.provider_financial_contract import ProviderFinancialValidationError
    with pytest.raises(ProviderFinancialValidationError) as exc:
        _command(original_component_public_id=UUID(int=9))
    assert exc.value.code == "original_component_forbidden"


@pytest.mark.parametrize("amount", ["0", "-1", "NaN", "1.000000001"])
def test_invalid_amounts_are_rejected(amount):
    from core.domain.finance.provider_financial_contract import ProviderFinancialValidationError
    with pytest.raises(ProviderFinancialValidationError) as exc:
        _command(amount=amount)
    assert exc.value.code == "invalid_amount"


def test_naive_occurred_at_is_rejected():
    from core.domain.finance.provider_financial_contract import ProviderFinancialValidationError
    with pytest.raises(ProviderFinancialValidationError) as exc:
        _command(occurred_at=datetime(2026, 8, 10, 9))
    assert exc.value.code == "timezone_required"


def test_engine_maps_every_component_to_approved_event_and_profile():
    source = ENGINE.read_text(encoding="utf-8")
    expected = {
        '"provider_fee":("PROVIDER_FEE_RECOGNIZED","recognition","provider_fee")',
        '"reserve_hold":("PROVIDER_SETTLEMENT_ADJUSTED","correction","provider_reserve_hold")',
        '"reserve_release":("PROVIDER_SETTLEMENT_ADJUSTED","correction","provider_reserve_release")',
        '"chargeback_loss":("PROVIDER_SETTLEMENT_ADJUSTED","correction","provider_chargeback_loss")',
    }
    assert all(fragment in source for fragment in expected)
    assert "AtomicPostedFinancialEventEngine.emit_and_post" in source


def test_repository_locks_only_authoritative_nonnullable_rows():
    source = REPOSITORY.read_text(encoding="utf-8")
    assert 'locking="FOR UPDATE OF s"' in source
    assert 'locking="FOR UPDATE OF c"' in source
    assert "LEFT JOIN" in source
    assert "FOR UPDATE\"" not in source


def test_repository_closes_governed_insert_window():
    source = REPOSITORY.read_text(encoding="utf-8")
    enabled = source.index("set_config('xbos.m46_component_authorized','on',true)")
    disabled = source.index("set_config('xbos.m46_component_authorized','off',true)")
    assert enabled < disabled


def test_net_projection_preserves_gross_truth():
    source = REPOSITORY.read_text(encoding="utf-8")
    assert "s.gross_amount-COALESCE" in source
    assert "UPDATE public.payment_settlements" not in source
    assert "UPDATE payment_settlements" not in ENGINE.read_text(encoding="utf-8")


@pytest.mark.parametrize("marker", [
    'DEVELOPMENT_DATABASE_NAME = "xbos_track_b_dev"',
    'TEST_DATABASE_NAME', "upgrade_downgrade_upgrade=PASS", "gross_immutable=PASS",
    "direct SQL component bypass succeeded", "outer transaction rollback leaked side effects",
])
def test_verifier_contains_release_gate(marker):
    assert marker in VERIFIER.read_text(encoding="utf-8")
