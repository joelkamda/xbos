"""Read-only M7.2 inventory/COGS and financial-document mapping verification."""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.domain.finance.legacy_authority_inventory import EXPECTED_HEAD, verify_no_writer_rerouting
from core.domain.finance.m6_acceptance import validate_release_manifest as validate_m6_manifest
from core.domain.finance.wnd_finance_adapter_contract import LegacyFinancialEnvelope, LegacySourceFamily
from core.domain.finance.wnd_inventory_document_contract import assert_document_replay, assert_inventory_replay
from core.domain.finance.wnd_inventory_document_service import (
    WndFinancialDocumentLinkageService, WndInventoryFinancialHandoffService,
)
from database import engine


def _envelope(family, record, payload):
    return LegacyFinancialEnvelope(
        tenant_id=2, organization_unit_id=1, source_family=family,
        source_record_type=record, source_record_id="72001",
        source_updated_at=datetime(2026, 8, 11, 17, 0, tzinfo=timezone.utc),
        business_date=date(2026, 8, 11), payload=payload,
        correlation_id=UUID("72000000-0000-0000-0000-000000000001"),
    )


def verify() -> None:
    if validate_m6_manifest(ROOT).canonical_head != EXPECTED_HEAD:
        raise RuntimeError("M6 freeze changed")
    verify_no_writer_rerouting(ROOT)
    inventory_payload = {
        "kind": "inventory_fulfillment", "movement_type": "sale", "inventory_movement_id": "72001",
        "atomic_unit_id": "44", "sale_id": "101", "quantity_delta": "-3", "unit_cost": "500",
        "currency_code": "XAF", "cost_basis_status": "verified", "cost_basis_provenance": "stock_receipt",
        "cost_basis_evidence_hash": "a" * 64, "fulfillment_nature": "restaurant_inventory",
    }
    ready = WndInventoryFinancialHandoffService.map(_envelope(
        LegacySourceFamily.INVENTORY, "inventory_movement", inventory_payload
    ))
    withheld = WndInventoryFinancialHandoffService.map(_envelope(
        LegacySourceFamily.INVENTORY, "inventory_movement", {
            **inventory_payload, "cost_basis_status": "missing", "unit_cost": None,
            "fulfillment_nature": "food_without_historical_cost",
        }
    ))
    document_payload = {
        "kind": "financial_document", "document_type": "receipt", "document_number": "R-0201-0826-00001",
        "issued_at": datetime(2026, 8, 11, 17, 0, tzinfo=timezone.utc), "content_hash": "b" * 64,
        "targets": [
            {"target_type": "commercial_event", "target_public_id": "72000000-0000-0000-0001-000000000001"},
            {"target_type": "payment_settlement", "target_public_id": "72000000-0000-0000-0002-000000000001"},
        ],
    }
    document = WndFinancialDocumentLinkageService.map(_envelope(
        LegacySourceFamily.DOCUMENT, "sale_receipt", document_payload
    ))
    assert_inventory_replay(ready, WndInventoryFinancialHandoffService.map(_envelope(
        LegacySourceFamily.INVENTORY, "inventory_movement", inventory_payload
    )))
    assert_document_replay(document, WndFinancialDocumentLinkageService.map(_envelope(
        LegacySourceFamily.DOCUMENT, "sale_receipt", document_payload
    )))
    if ready.command is None or ready.command.event_type_code != "COST_OF_FULFILLMENT_RECOGNIZED":
        raise RuntimeError("verified COGS handoff missing")
    if "no_revenue" not in ready.command.canonical_payload()["economic_effects"]:
        raise RuntimeError("fulfillment handoff created revenue")
    if withheld.command is not None or withheld.disposition_reason != "missing_reliable_cost_basis":
        raise RuntimeError("missing historical cost was fabricated")
    if document.regeneration_allowed or not document.original_artifact_preserved:
        raise RuntimeError("historical receipt identity was not preserved")
    with engine.connect() as connection:
        database = connection.execute(text("SELECT current_database()" )).scalar_one()
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if database != "xbos_track_b_dev" or revision != EXPECTED_HEAD:
            raise RuntimeError(f"unexpected development authority={database}:{revision}")
    print(f"database={database}")
    print(f"revision={revision}")
    print("m72_wnd_inventory_document_mapping=PASS verified_cogs=PASS missing_cost_withheld=PASS receipt_linkage=PASS")
    print("m72_mapping_boundary=PASS inventory_quantity_authority=UNCHANGED no_fake_cogs=PASS no_revenue=PASS document_regeneration=FORBIDDEN writer_routing=UNCHANGED cutover_owner=R6 migration=NONE")


if __name__ == "__main__":
    verify()
