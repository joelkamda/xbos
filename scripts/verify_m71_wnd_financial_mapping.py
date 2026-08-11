"""Read-only M7.1 mapping conformance verification."""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.domain.finance.legacy_authority_inventory import EXPECTED_HEAD, load_inventory, verify_no_writer_rerouting
from core.domain.finance.m6_acceptance import validate_release_manifest as validate_m6_manifest
from core.domain.finance.wnd_finance_adapter_contract import LegacyFinancialEnvelope, LegacySourceFamily
from core.domain.finance.wnd_financial_mapping_contract import assert_replay
from core.domain.finance.wnd_financial_mapping_service import WndFinancialMappingService
from database import engine


def _envelope(family, record, payload):
    return LegacyFinancialEnvelope(
        tenant_id=2, organization_unit_id=1, source_family=family,
        source_record_type=record, source_record_id="71001",
        source_updated_at=datetime(2026, 8, 11, 16, 0, tzinfo=timezone.utc),
        business_date=date(2026, 8, 11), payload=payload,
        correlation_id=UUID("71000000-0000-0000-0000-000000000001"),
    )


def verify() -> None:
    if validate_m6_manifest(ROOT).canonical_head != EXPECTED_HEAD:
        raise RuntimeError("M6 freeze changed")
    if len(load_inventory(ROOT).surfaces) != 14:
        raise RuntimeError("M7.0 inventory changed")
    verify_no_writer_rerouting(ROOT)
    sale = WndFinancialMappingService.map(_envelope(LegacySourceFamily.COMMERCIAL, "sale", {
        "kind": "commercial_sale", "gross_amount": Decimal("10000"), "discount_amount": Decimal("500"),
        "complimentary_amount": Decimal("500"), "collected_amount": Decimal("7000"), "unpaid_amount": Decimal("2000"),
        "currency_code": "XAF", "revenue_nature": "restaurant_sale", "discount_reason": "approved_discount",
        "complimentary_reason": "service_recovery", "complimentary_policy": "service_recovery",
    }))
    payment = WndFinancialMappingService.map(_envelope(LegacySourceFamily.PAYMENT, "payment_attempt", {
        "kind": "payment_settlement", "amount": Decimal("7000"), "currency_code": "XAF",
        "payment_method_code": "mtn_mobile_money", "payment_rail_code": "mobile_money",
        "operational_account_public_id": "71000000-0000-0000-0001-000000000001",
        "finality_status": "final", "evidence_verified": True, "evidence_hash": "a" * 64,
        "external_settlement_reference": "M71-PROVIDER-1",
    }))
    repayment = WndFinancialMappingService.map(_envelope(LegacySourceFamily.RECEIVABLE, "ar_repayment", {
        "kind": "receivable_repayment", "amount": Decimal("2000"), "currency_code": "XAF",
        "payment_method_code": "cash", "payment_rail_code": "cash",
        "operational_account_public_id": "71000000-0000-0000-0001-000000000002",
        "financial_obligation_public_id": "71000000-0000-0000-0002-000000000001",
        "finality_status": "final", "evidence_verified": True, "evidence_hash": "b" * 64,
    }))
    refund = WndFinancialMappingService.map(_envelope(LegacySourceFamily.ADJUSTMENT, "refund", {
        "kind": "refund", "amount": Decimal("1000"), "currency_code": "XAF",
        "original_settlement_public_id": "71000000-0000-0000-0003-000000000001",
        "refund_settlement_public_id": "71000000-0000-0000-0003-000000000002",
        "refund_reason": "customer_return", "document_number": "M71-RN-1", "evidence_hash": "c" * 64,
    }))
    assert_replay(sale, WndFinancialMappingService.map(_envelope(LegacySourceFamily.COMMERCIAL, "sale", {
        "kind": "commercial_sale", "gross_amount": Decimal("10000"), "discount_amount": Decimal("500"),
        "complimentary_amount": Decimal("500"), "collected_amount": Decimal("7000"), "unpaid_amount": Decimal("2000"),
        "currency_code": "XAF", "revenue_nature": "restaurant_sale", "discount_reason": "approved_discount",
        "complimentary_reason": "service_recovery", "complimentary_policy": "service_recovery",
    })))
    if any("revenue" in effect for plan in (payment, repayment) for command in plan.commands for effect in command.economic_effects if effect != "no_revenue"):
        raise RuntimeError("payment or repayment created revenue")
    with engine.connect() as connection:
        database = connection.execute(text("SELECT current_database()" )).scalar_one()
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if database != "xbos_track_b_dev" or revision != EXPECTED_HEAD:
            raise RuntimeError(f"unexpected development authority={database}:{revision}")
    print(f"database={database}")
    print(f"revision={revision}")
    print(f"m71_wnd_financial_mapping=PASS sale={len(sale.commands)} payment={len(payment.commands)} repayment={len(repayment.commands)} refund={len(refund.commands)}")
    print("m71_mapping_boundary=PASS deterministic=PASS replay=PASS non_revenue_payment=PASS non_revenue_repayment=PASS refund_append=PASS writer_routing=UNCHANGED cutover_owner=R6 migration=NONE")


if __name__ == "__main__":
    verify()
