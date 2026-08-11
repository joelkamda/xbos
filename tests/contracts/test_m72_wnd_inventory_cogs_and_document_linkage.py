from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from core.domain.finance.wnd_finance_adapter_contract import LegacyFinancialEnvelope, LegacySourceFamily
from core.domain.finance.wnd_inventory_document_contract import (
    WndInventoryDocumentError, assert_document_replay, assert_inventory_replay,
)
from core.domain.finance.wnd_inventory_document_service import (
    WndFinancialDocumentLinkageService, WndInventoryFinancialHandoffService,
)

ROOT = Path(__file__).resolve().parents[2]
BASE = datetime(2026, 8, 11, 17, 0, tzinfo=timezone.utc)


def envelope(family, payload, *, source_id="1"):
    return LegacyFinancialEnvelope(
        tenant_id=2, organization_unit_id=1, source_family=family,
        source_record_type=str(payload["kind"]), source_record_id=source_id,
        source_updated_at=BASE, business_date=date(2026, 8, 11), payload=payload,
        correlation_id=UUID("72000000-0000-0000-0000-000000000001"),
    )


def movement(**changes):
    payload = {
        "kind": "inventory_fulfillment", "movement_type": "sale", "inventory_movement_id": "901",
        "atomic_unit_id": "44", "sale_id": "101", "quantity_delta": "-3", "unit_cost": "500",
        "currency_code": "XAF", "cost_basis_status": "verified",
        "cost_basis_provenance": "stock_receipt", "cost_basis_evidence_hash": "a" * 64,
        "fulfillment_nature": "restaurant_inventory",
    }
    payload.update(changes)
    return envelope(LegacySourceFamily.INVENTORY, payload)


def document(**changes):
    payload = {
        "kind": "financial_document", "document_type": "receipt", "document_number": "R-0201-0826-00001",
        "issued_at": BASE, "content_hash": "b" * 64,
        "targets": [
            {"target_type": "commercial_event", "target_public_id": "72000000-0000-0000-0001-000000000001"},
            {"target_type": "payment_settlement", "target_public_id": "72000000-0000-0000-0002-000000000001"},
        ],
    }
    payload.update(changes)
    return envelope(LegacySourceFamily.DOCUMENT, payload)


def test_contract_is_schema_neutral_and_r6_keeps_cutover():
    contract = json.loads((ROOT / "contracts/finance/v1/m72_wnd_inventory_cogs_and_document_linkage.json").read_text(encoding="utf-8"))
    assert contract["canonical_head"] == "m64_reconciliation_controls_020"
    assert contract["source_commit"] == "1bc83f7"
    assert contract["migration"] is False
    assert contract["execution_mode"] == "mapping_plan_only"
    assert contract["writer_routing"] == "unchanged"
    assert contract["live_cutover_owner"] == "R6"


def test_verified_fulfillment_cost_maps_exact_canonical_event():
    plan = WndInventoryFinancialHandoffService.map(movement())
    assert plan.disposition == "ready"
    assert plan.command.event_type_code == "COST_OF_FULFILLMENT_RECOGNIZED"
    assert plan.command.amount == Decimal("1500")
    assert plan.command.quantity == Decimal("3")
    assert plan.command.unit_cost == Decimal("500")
    assert plan.command.payload["posting_context"]["posting_profile_code"] == "fulfillment_cost"
    assert "no_revenue" in plan.command.canonical_payload()["economic_effects"]


@pytest.mark.parametrize("status", ["missing", "unverified", "legacy_unknown", ""])
def test_missing_or_unverified_cost_is_withheld_without_fake_zero_cogs(status):
    plan = WndInventoryFinancialHandoffService.map(movement(cost_basis_status=status, unit_cost="0"))
    assert plan.disposition == "withheld"
    assert plan.disposition_reason == "missing_reliable_cost_basis"
    assert plan.command is None


def test_historical_food_without_cost_is_not_fabricated():
    plan = WndInventoryFinancialHandoffService.map(movement(
        cost_basis_status="missing", unit_cost=None, fulfillment_nature="food_without_historical_cost"
    ))
    assert plan.command is None


@pytest.mark.parametrize("movement_type", ["stock_in", "opening", "adjustment", "transfer"])
def test_non_fulfillment_inventory_movement_cannot_create_cogs(movement_type):
    with pytest.raises(WndInventoryDocumentError) as raised:
        WndInventoryFinancialHandoffService.map(movement(movement_type=movement_type))
    assert raised.value.code == "non_fulfillment_movement"


@pytest.mark.parametrize("delta", ["0", "1", "3"])
def test_fulfillment_requires_outbound_quantity(delta):
    with pytest.raises(WndInventoryDocumentError) as raised:
        WndInventoryFinancialHandoffService.map(movement(quantity_delta=delta))
    assert raised.value.code == "outbound_quantity_required"


@pytest.mark.parametrize("unit_cost", ["0", "-1", "NaN"])
def test_verified_cost_basis_requires_positive_finite_unit_cost(unit_cost):
    with pytest.raises(Exception):
        WndInventoryFinancialHandoffService.map(movement(unit_cost=unit_cost))


def test_cost_extension_is_exact_decimal_not_float():
    plan = WndInventoryFinancialHandoffService.map(movement(quantity_delta="-1.5", unit_cost="0.10"))
    assert plan.command.amount == Decimal("0.150")


@pytest.mark.parametrize("provenance", ["current_item_metadata", "inferred", "guess", ""])
def test_mutable_or_unapproved_cost_provenance_fails_closed(provenance):
    with pytest.raises(WndInventoryDocumentError):
        WndInventoryFinancialHandoffService.map(movement(cost_basis_provenance=provenance))


def test_inventory_mapping_replay_is_stable_and_conflict_fails_closed():
    first = WndInventoryFinancialHandoffService.map(movement())
    same = WndInventoryFinancialHandoffService.map(movement())
    assert assert_inventory_replay(first, same) is first
    changed = WndInventoryFinancialHandoffService.map(movement(unit_cost="501"))
    with pytest.raises(WndInventoryDocumentError) as raised:
        assert_inventory_replay(first, changed)
    assert raised.value.code == "mapping_idempotency_conflict"


def test_receipt_links_to_canonical_facts_without_becoming_authority():
    plan = WndFinancialDocumentLinkageService.map(document())
    assert plan.document_number == "R-0201-0826-00001"
    assert [item.target_type for item in plan.targets] == ["commercial_event", "payment_settlement"]
    assert plan.original_artifact_preserved is True
    assert plan.regeneration_allowed is False
    assert plan.execution_allowed is False


def test_historical_receipt_identity_and_content_hash_are_stable():
    first = WndFinancialDocumentLinkageService.map(document())
    same = WndFinancialDocumentLinkageService.map(document())
    assert assert_document_replay(first, same) is first
    assert first.plan_fingerprint == same.plan_fingerprint


def test_changed_content_under_same_receipt_number_conflicts():
    first = WndFinancialDocumentLinkageService.map(document())
    changed = WndFinancialDocumentLinkageService.map(document(content_hash="c" * 64))
    with pytest.raises(WndInventoryDocumentError) as raised:
        assert_document_replay(first, changed)
    assert raised.value.code == "document_idempotency_conflict"


@pytest.mark.parametrize("value", ["A" * 64, "a" * 63, "x" * 64, ""])
def test_document_content_hash_must_be_lowercase_sha256(value):
    with pytest.raises(Exception):
        WndFinancialDocumentLinkageService.map(document(content_hash=value))


def test_document_requires_timezone_and_at_least_one_supported_target():
    with pytest.raises(WndInventoryDocumentError):
        WndFinancialDocumentLinkageService.map(document(issued_at=datetime(2026, 8, 11, 17, 0)))
    with pytest.raises(WndInventoryDocumentError):
        WndFinancialDocumentLinkageService.map(document(targets=[]))
    with pytest.raises(WndInventoryDocumentError):
        WndFinancialDocumentLinkageService.map(document(targets=[{
            "target_type": "inventory_cache", "target_public_id": "72000000-0000-0000-0001-000000000001"
        }]))


def test_wrong_source_families_fail_closed():
    with pytest.raises(WndInventoryDocumentError):
        WndInventoryFinancialHandoffService.map(document())
    with pytest.raises(WndInventoryDocumentError):
        WndFinancialDocumentLinkageService.map(movement())


def test_no_m72_migration_execution_or_writer_routing_exists():
    assert not tuple((ROOT / "alembic_neutral/versions").glob("m72_*.py"))
    marker = (ROOT / "core/persistence/m72_wnd_inventory_document_mapping.py").read_text(encoding="utf-8")
    assert "SCHEMA_NEUTRAL = True" in marker
    assert "EXECUTES_CANONICAL_COMMANDS = False" in marker
    assert "REROUTES_LEGACY_WRITERS = False" in marker
    assert "REGENERATES_HISTORICAL_DOCUMENTS = False" in marker


def test_gate_and_install_artifacts_exist():
    assert (ROOT / "XBOS_M7_2_RUN_ACCEPTANCE.cmd").is_file()
    assert (ROOT / "XBOS_M7_2_INSTALL_AND_VERIFY.txt").is_file()
