"""WND/Restaurant specimen profile for the neutral M8.4 conformance harness."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Mapping
from uuid import UUID

from .pack_conformance_contract import ControlTotalSet, PackConformanceProfile, PackFlowEvidence, semantic_fingerprint
from .wnd_finance_adapter_contract import LegacyFinancialEnvelope, LegacySourceFamily
from .wnd_financial_mapping_contract import CanonicalMappingPlan, assert_replay
from .wnd_financial_mapping_service import WndFinancialMappingService
from .wnd_inventory_document_contract import assert_document_replay, assert_inventory_replay
from .wnd_inventory_document_service import WndFinancialDocumentLinkageService, WndInventoryFinancialHandoffService
from .wnd_shadow_rehearsal_service import WndShadowRehearsalService

BASE = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
TENANT_ID = 2
ORGANIZATION_UNIT_ID = 1


def _envelope(family: LegacySourceFamily, kind: str, source_id: str, payload: Mapping[str, Any]) -> LegacyFinancialEnvelope:
    return LegacyFinancialEnvelope(
        tenant_id=TENANT_ID, organization_unit_id=ORGANIZATION_UNIT_ID,
        source_family=family, source_record_type=kind, source_record_id=source_id,
        source_updated_at=BASE, business_date=date(2026, 8, 12), payload={"kind": kind, **payload},
        correlation_id=UUID("84000000-0000-0000-0000-000000000099"),
    )


def _totals(values: Mapping[str, Any]) -> ControlTotalSet:
    return ControlTotalSet("XAF", {name: Decimal(str(value)) for name, value in values.items()})


def _financial_evidence(flow_code: str, envelope: LegacyFinancialEnvelope) -> PackFlowEvidence:
    plan = WndFinancialMappingService.map(envelope)
    replay = WndFinancialMappingService.map(envelope)
    assert_replay(plan, replay)
    case = WndShadowRehearsalService.financial_case(1, plan)
    observed = _totals(case.expected.values)
    effects = tuple(str(item.public_id) for item in plan.commands)
    return PackFlowEvidence(
        flow_code=flow_code, source_identity=plan.source_identity,
        tenant_id=plan.tenant_id, organization_unit_id=plan.organization_unit_id,
        mapping_fingerprint=plan.plan_fingerprint,
        effect_bundle_fingerprint=semantic_fingerprint(effects), canonical_effect_ids=effects,
        expected=_totals(case.expected.values), observed=observed,
    )


def commercial_sale_envelope(*, gross_amount: str = "10000") -> LegacyFinancialEnvelope:
    return _envelope(LegacySourceFamily.COMMERCIAL, "commercial_sale", "sale-8401", {
        "gross_amount": gross_amount, "discount_amount": "500", "complimentary_amount": "500",
        "collected_amount": "7000", "unpaid_amount": "2000", "currency_code": "XAF",
        "revenue_nature": "restaurant_sale", "discount_reason": "approved_discount",
        "complimentary_reason": "service_recovery", "complimentary_policy": "service_recovery",
    })


def build_wnd_conformance_profile() -> PackConformanceProfile:
    flows = [
        _financial_evidence("commercial_sale", commercial_sale_envelope()),
        _financial_evidence("payment_collection", _envelope(LegacySourceFamily.PAYMENT, "payment_settlement", "payment-8401", {
            "amount": "7000", "fee_amount": "0", "currency_code": "XAF", "payment_method_code": "cash",
            "payment_rail_code": "cash", "operational_account_public_id": "84000000-0000-0000-0001-000000000001",
            "finality_status": "final", "evidence_verified": True, "evidence_hash": "a" * 64,
        })),
        _financial_evidence("receivable_repayment", _envelope(LegacySourceFamily.RECEIVABLE, "receivable_repayment", "repayment-8401", {
            "amount": "2000", "fee_amount": "0", "currency_code": "XAF", "payment_method_code": "cash",
            "payment_rail_code": "cash", "operational_account_public_id": "84000000-0000-0000-0001-000000000001",
            "financial_obligation_public_id": "84000000-0000-0000-0002-000000000001",
            "finality_status": "final", "evidence_verified": True, "evidence_hash": "b" * 64,
        })),
        _financial_evidence("refund_reversal", _envelope(LegacySourceFamily.ADJUSTMENT, "refund", "refund-8401", {
            "amount": "500", "currency_code": "XAF",
            "original_settlement_public_id": "84000000-0000-0000-0003-000000000001",
            "refund_settlement_public_id": "84000000-0000-0000-0003-000000000002",
            "refund_reason": "customer_return", "document_number": "RN-8401", "evidence_hash": "c" * 64,
        })),
    ]
    inventory_envelope = _envelope(LegacySourceFamily.INVENTORY, "inventory_fulfillment", "inventory-8401", {
        "movement_type": "sale", "inventory_movement_id": "8401", "atomic_unit_id": "44", "sale_id": "sale-8401",
        "quantity_delta": "-3", "unit_cost": "500", "currency_code": "XAF", "cost_basis_status": "verified",
        "cost_basis_provenance": "stock_receipt", "cost_basis_evidence_hash": "d" * 64,
        "fulfillment_nature": "restaurant_inventory",
    })
    inventory = WndInventoryFinancialHandoffService.map(inventory_envelope)
    assert_inventory_replay(inventory, WndInventoryFinancialHandoffService.map(inventory_envelope))
    inventory_case = WndShadowRehearsalService.inventory_case(1, inventory)
    flows.append(PackFlowEvidence(
        "inventory_cogs", inventory.source_identity, inventory.tenant_id, inventory.organization_unit_id,
        inventory.plan_fingerprint, semantic_fingerprint((str(inventory.command.public_id),)),
        (str(inventory.command.public_id),), _totals(inventory_case.expected.values), _totals(inventory_case.expected.values),
    ))
    document_envelope = _envelope(LegacySourceFamily.DOCUMENT, "financial_document", "document-8401", {
        "document_type": "receipt", "document_number": "R-8401", "issued_at": BASE, "content_hash": "e" * 64,
        "targets": (
            {"target_type": "commercial_event", "target_public_id": "84000000-0000-0000-0004-000000000001"},
            {"target_type": "payment_settlement", "target_public_id": "84000000-0000-0000-0004-000000000002"},
        ),
    })
    document = WndFinancialDocumentLinkageService.map(document_envelope)
    assert_document_replay(document, WndFinancialDocumentLinkageService.map(document_envelope))
    document_case = WndShadowRehearsalService.document_case(1, document, currency_code="XAF")
    target_ids = tuple(str(item.target_public_id) for item in document.targets)
    flows.append(PackFlowEvidence(
        "document_receipt_handoff", document.source_identity, document.tenant_id, document.organization_unit_id,
        document.plan_fingerprint, semantic_fingerprint(target_ids), target_ids,
        _totals(document_case.expected.values), _totals(document_case.expected.values),
    ))
    return PackConformanceProfile(
        pack_code="wnd.restaurant", pack_version="m7-frozen-b1ec385",
        authoritative_sources=(
            "commercial_transactions", "payment_records", "customer_debts", "sale_adjustments",
            "inventory_movements", "financial_documents", "reconciliation_control_totals",
        ),
        flows=tuple(flows),
        known_exclusions=("live_operational_cutover", "legacy_writer_retirement", "unverified_historical_food_cost"),
    )


def first_canonical_plan() -> CanonicalMappingPlan:
    return WndFinancialMappingService.map(commercial_sale_envelope())
