from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from core.domain.finance.legacy_authority_contract import LegacyAuthorityError
from core.domain.finance.legacy_authority_inventory import EXPECTED_HEAD, load_inventory, verify_no_writer_rerouting
from core.domain.finance.wnd_finance_adapter_contract import AdapterAssessment, LegacyFinancialEnvelope, LegacySourceFamily

ROOT = Path(__file__).resolve().parents[2]


def _envelope(payload=None):
    return LegacyFinancialEnvelope(
        tenant_id=1,
        organization_unit_id=2,
        source_family=LegacySourceFamily.COMMERCIAL,
        source_record_type="sale",
        source_record_id="42",
        source_updated_at=datetime(2026, 8, 11, 15, 0, tzinfo=timezone.utc),
        business_date=date(2026, 8, 11),
        payload=payload or {"amount": Decimal("1000.00"), "currency": "XAF"},
        correlation_id=UUID("70000000-0000-0000-0000-000000000001"),
    )


def test_contract_is_schema_neutral_and_preserves_r6_cutover():
    contract = json.loads((ROOT / "contracts/finance/v1/m70_legacy_financial_authority_inventory_and_adapter_boundary.json").read_text(encoding="utf-8"))
    assert contract["canonical_head"] == EXPECTED_HEAD
    assert contract["migration"] is False
    assert contract["writer_routing"] == "unchanged"
    assert contract["live_cutover_owner"] == "R6"
    assert contract["adapter_mode"] == "inventory_and_assessment_only"


def test_inventory_resolves_all_fourteen_legacy_surfaces():
    inventory = load_inventory(ROOT)
    assert len(inventory.surfaces) == 14
    assert len({surface.code for surface in inventory.surfaces}) == 14
    assert {surface.mapping_package for surface in inventory.surfaces} == {"M7.1", "M7.2", "M7.3", "M7.4"}


def test_inventory_covers_required_financial_families():
    codes = {surface.code for surface in load_inventory(ROOT).surfaces}
    assert {
        "commercial_sale_writer", "payment_settlement_writer", "xafpay_callback_writer",
        "receivable_writer", "receivable_repayment_writer", "refund_event_writer",
        "inventory_movement_writer", "receipt_projection_reader",
        "legacy_reconciliation_writer", "legacy_statement_reader",
    } <= codes


def test_every_writer_has_store_target_and_later_disposition():
    for surface in load_inventory(ROOT).surfaces:
        assert surface.legacy_stores
        assert surface.canonical_targets
        assert surface.mapping_package != "M7.0"
        assert surface.disposition.value in {
            "shadow_candidate", "control_total_source", "dual_read_candidate", "retirement_candidate"
        }


def test_adapter_envelope_has_exact_deterministic_fingerprint():
    first = _envelope()
    second = _envelope({"currency": "XAF", "amount": Decimal("1000.00")})
    assert first.source_identity == "sale:42"
    assert first.payload_fingerprint == second.payload_fingerprint
    assert len(first.payload_fingerprint) == 64


def test_adapter_fingerprint_never_converts_decimal_to_float():
    whole = _envelope({"amount": Decimal("0.100000000000000001")})
    rounded = _envelope({"amount": Decimal("0.1")})
    assert whole.payload_fingerprint != rounded.payload_fingerprint


@pytest.mark.parametrize("tenant,organization", [(0, 1), (1, 0), (-1, 1)])
def test_adapter_scope_fails_closed(tenant, organization):
    with pytest.raises(LegacyAuthorityError) as raised:
        LegacyFinancialEnvelope(
            tenant_id=tenant,
            organization_unit_id=organization,
            source_family=LegacySourceFamily.PAYMENT,
            source_record_type="payment",
            source_record_id="1",
            source_updated_at=datetime.now(timezone.utc),
            business_date=date.today(),
            payload={},
        )
    assert raised.value.code == "invalid_scope"


def test_m70_assessment_cannot_enable_execution():
    with pytest.raises(LegacyAuthorityError) as raised:
        AdapterAssessment("sale:42", "a" * 64, "M7.1", ("financial_events",), execution_allowed=True)
    assert raised.value.code == "m70_execution_forbidden"


def test_no_legacy_writer_or_api_is_rerouted_to_m70():
    verify_no_writer_rerouting(ROOT)


def test_persistence_marker_is_schema_neutral():
    source = (ROOT / "core/persistence/m70_finance_migration_support.py").read_text(encoding="utf-8")
    assert "SCHEMA_NEUTRAL = True" in source
    assert "WRITES_NEW_TABLES = False" in source
    assert "REROUTES_LEGACY_WRITERS = False" in source
    assert 'LIVE_CUTOVER_OWNER = "R6"' in source


def test_no_m70_migration_exists():
    assert not tuple((ROOT / "alembic_neutral/versions").glob("m70_*.py"))


def test_verifier_gate_and_instructions_exist():
    assert (ROOT / "scripts/verify_m70_legacy_financial_authority.py").is_file()
    assert (ROOT / "XBOS_M7_0_RUN_ACCEPTANCE.cmd").is_file()
    assert (ROOT / "XBOS_M7_0_INSTALL_AND_VERIFY.txt").is_file()
