"""Deterministic M7.2 WND inventory/COGS handoff and document linkage."""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping
from uuid import NAMESPACE_URL, UUID, uuid5

from .wnd_finance_adapter_contract import LegacyFinancialEnvelope, LegacySourceFamily
from .wnd_financial_mapping_contract import money, require_hash
from .wnd_inventory_document_contract import (
    FinancialDocumentLinkagePlan,
    FinancialDocumentTarget,
    FulfillmentCostCommandDescriptor,
    InventoryFinancialHandoffPlan,
    WndInventoryDocumentError,
)


_NAMESPACE = uuid5(NAMESPACE_URL, "xbos:m72:wnd-inventory-document:v1")


def _text(payload: Mapping[str, Any], name: str) -> str:
    value = str(payload.get(name, "")).strip()
    if not value:
        raise WndInventoryDocumentError("required_field_missing", name)
    return value


def _uuid(value: Any, name: str) -> UUID:
    try:
        selected = UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise WndInventoryDocumentError("invalid_uuid", name) from exc
    if selected.int == 0:
        raise WndInventoryDocumentError("invalid_uuid", name)
    return selected


def _currency(payload: Mapping[str, Any]) -> str:
    value = _text(payload, "currency_code").upper()
    if len(value) != 3 or not value.isalpha():
        raise WndInventoryDocumentError("invalid_currency", value)
    return value


class WndInventoryFinancialHandoffService:
    @classmethod
    def map(cls, envelope: LegacyFinancialEnvelope) -> InventoryFinancialHandoffPlan:
        if envelope.source_family is not LegacySourceFamily.INVENTORY:
            raise WndInventoryDocumentError("source_family_mismatch", envelope.source_family.value)
        source = envelope.payload
        if str(source.get("kind", "")).strip().lower() != "inventory_fulfillment":
            raise WndInventoryDocumentError("unsupported_mapping_kind", str(source.get("kind", "")))
        movement_type = _text(source, "movement_type").lower()
        if movement_type not in {"sale", "fulfillment"}:
            raise WndInventoryDocumentError("non_fulfillment_movement", movement_type)
        quantity_delta = Decimal(str(source.get("quantity_delta", "0")))
        if not quantity_delta.is_finite() or quantity_delta >= 0 or quantity_delta.as_tuple().exponent < -8:
            raise WndInventoryDocumentError("outbound_quantity_required", str(quantity_delta))
        quantity = -quantity_delta
        source_identity = envelope.source_identity
        status = str(source.get("cost_basis_status", "missing")).strip().lower()
        if status != "verified":
            return InventoryFinancialHandoffPlan(
                tenant_id=envelope.tenant_id,
                organization_unit_id=envelope.organization_unit_id,
                source_identity=source_identity,
                source_fingerprint=envelope.payload_fingerprint,
                disposition="withheld",
                disposition_reason="missing_reliable_cost_basis",
                command=None,
            )
        unit_cost = money(source.get("unit_cost"), "unit_cost", allow_zero=False)
        amount = quantity * unit_cost
        provenance = _text(source, "cost_basis_provenance").lower()
        evidence_hash = require_hash(source.get("cost_basis_evidence_hash"), "cost_basis_evidence_hash")
        public_id = uuid5(_NAMESPACE, f"{envelope.tenant_id}:{source_identity}:fulfillment-cost")
        correlation_id = envelope.correlation_id or uuid5(_NAMESPACE, f"{envelope.tenant_id}:{source_identity}:correlation")
        command = FulfillmentCostCommandDescriptor(
            public_id=public_id,
            amount=amount,
            currency_code=_currency(source),
            quantity=quantity,
            unit_cost=unit_cost,
            cost_basis_provenance=provenance,
            evidence_hash=evidence_hash,
            payload={
                "tenant_id": envelope.tenant_id,
                "organization_unit_id": envelope.organization_unit_id,
                "source_component": "wnd_finance_adapter",
                "source_record_id": envelope.source_record_id,
                "inventory_movement_id": _text(source, "inventory_movement_id"),
                "atomic_unit_id": _text(source, "atomic_unit_id"),
                "sale_id": str(source.get("sale_id") or "").strip() or None,
                "quantity_delta": quantity_delta,
                "event_version": 1,
                "amount": amount,
                "currency_code": _currency(source),
                "economic_role": "recognition",
                "source_record_kind": "fulfillment_cost_snapshot",
                "posting_context": {"posting_profile_code": "fulfillment_cost"},
                "classification_snapshot": {
                    "cost_nature": {"code": _text(source, "fulfillment_nature").lower()},
                    "cost_basis_provenance": {"code": provenance},
                },
                "occurred_at": envelope.source_updated_at,
                "business_date": envelope.business_date,
                "correlation_id": correlation_id,
                "idempotency_scope": "m72.inventory_fulfillment",
                "idempotency_key": f"m72.inventory_fulfillment:{source_identity}",
                "source_payload_fingerprint": envelope.payload_fingerprint,
                "evidence_hash": evidence_hash,
            },
        )
        return InventoryFinancialHandoffPlan(
            tenant_id=envelope.tenant_id,
            organization_unit_id=envelope.organization_unit_id,
            source_identity=source_identity,
            source_fingerprint=envelope.payload_fingerprint,
            disposition="ready",
            disposition_reason="verified_cost_basis_available",
            command=command,
        )


class WndFinancialDocumentLinkageService:
    @classmethod
    def map(cls, envelope: LegacyFinancialEnvelope) -> FinancialDocumentLinkagePlan:
        if envelope.source_family is not LegacySourceFamily.DOCUMENT:
            raise WndInventoryDocumentError("source_family_mismatch", envelope.source_family.value)
        source = envelope.payload
        if str(source.get("kind", "")).strip().lower() != "financial_document":
            raise WndInventoryDocumentError("unsupported_mapping_kind", str(source.get("kind", "")))
        raw_targets = source.get("targets")
        if not isinstance(raw_targets, (list, tuple)) or not raw_targets:
            raise WndInventoryDocumentError("document_targets_invalid", envelope.source_identity)
        targets = tuple(FinancialDocumentTarget(
            target_type=_text(item, "target_type"),
            target_public_id=_uuid(item.get("target_public_id"), "target_public_id"),
        ) for item in raw_targets if isinstance(item, Mapping))
        if len(targets) != len(raw_targets):
            raise WndInventoryDocumentError("document_targets_invalid", envelope.source_identity)
        issued_at = source.get("issued_at")
        if not hasattr(issued_at, "tzinfo"):
            raise WndInventoryDocumentError("issued_at_required", envelope.source_identity)
        return FinancialDocumentLinkagePlan(
            tenant_id=envelope.tenant_id,
            organization_unit_id=envelope.organization_unit_id,
            source_identity=envelope.source_identity,
            source_fingerprint=envelope.payload_fingerprint,
            document_type=_text(source, "document_type"),
            document_number=_text(source, "document_number"),
            issued_at=issued_at,
            content_hash=require_hash(source.get("content_hash"), "content_hash"),
            targets=targets,
        )
