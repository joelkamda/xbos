"""Typed, side-effect-free M7.2 inventory handoff and document-link plans."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping
from uuid import UUID

from .wnd_financial_mapping_contract import fingerprint, money, require_hash


CONTRACT_CODE = "XBOS_M72_WND_INVENTORY_COGS_AND_DOCUMENT_LINKAGE"
CONTRACT_VERSION = 1


class WndInventoryDocumentError(ValueError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class FulfillmentCostCommandDescriptor:
    public_id: UUID
    amount: Decimal
    currency_code: str
    quantity: Decimal
    unit_cost: Decimal
    cost_basis_provenance: str
    evidence_hash: str
    payload: Mapping[str, Any]
    execution_allowed: bool = False
    command_type: str = "CanonicalFinancialEventCommand"
    contract_code: str = "XBOS_M21_CANONICAL_EVENT_ENGINE"
    event_type_code: str = "COST_OF_FULFILLMENT_RECOGNIZED"
    posting_profile_code: str = "fulfillment_cost"
    command_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "public_id", UUID(str(self.public_id)))
        object.__setattr__(self, "amount", money(self.amount, "amount", allow_zero=False))
        object.__setattr__(self, "quantity", money(self.quantity, "quantity", allow_zero=False))
        object.__setattr__(self, "unit_cost", money(self.unit_cost, "unit_cost", allow_zero=False))
        object.__setattr__(self, "currency_code", str(self.currency_code).strip().upper())
        object.__setattr__(self, "evidence_hash", require_hash(self.evidence_hash))
        object.__setattr__(self, "payload", dict(self.payload))
        if len(self.currency_code) != 3 or not self.currency_code.isalpha():
            raise WndInventoryDocumentError("invalid_currency", self.currency_code)
        if self.amount != self.quantity * self.unit_cost:
            raise WndInventoryDocumentError("cost_extension_mismatch", str(self.public_id))
        if self.cost_basis_provenance not in {
            "approved_cost_snapshot", "stock_receipt", "inventory_movement_snapshot"
        }:
            raise WndInventoryDocumentError("unsupported_cost_provenance", self.cost_basis_provenance)
        if self.execution_allowed:
            raise WndInventoryDocumentError("m72_execution_forbidden", str(self.public_id))
        object.__setattr__(self, "command_fingerprint", fingerprint(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "contract_code": self.contract_code,
            "command_type": self.command_type,
            "public_id": str(self.public_id),
            "event_type_code": self.event_type_code,
            "posting_profile_code": self.posting_profile_code,
            "amount": self.amount,
            "currency_code": self.currency_code,
            "quantity": self.quantity,
            "unit_cost": self.unit_cost,
            "cost_basis_provenance": self.cost_basis_provenance,
            "evidence_hash": self.evidence_hash,
            "payload": self.payload,
            "economic_effects": ("fulfillment_expense_increase", "inventory_asset_decrease", "no_revenue"),
            "execution_allowed": False,
        }


@dataclass(frozen=True)
class InventoryFinancialHandoffPlan:
    tenant_id: int
    organization_unit_id: int
    source_identity: str
    source_fingerprint: str
    disposition: str
    disposition_reason: str
    command: FulfillmentCostCommandDescriptor | None
    writer_routing: str = "unchanged"
    execution_allowed: bool = False
    plan_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if min(self.tenant_id, self.organization_unit_id) <= 0:
            raise WndInventoryDocumentError("invalid_scope", self.source_identity)
        if self.disposition not in {"ready", "withheld"}:
            raise WndInventoryDocumentError("invalid_disposition", self.disposition)
        if (self.disposition == "ready") != (self.command is not None):
            raise WndInventoryDocumentError("command_disposition_mismatch", self.source_identity)
        if not self.disposition_reason:
            raise WndInventoryDocumentError("disposition_reason_required", self.source_identity)
        if self.writer_routing != "unchanged" or self.execution_allowed:
            raise WndInventoryDocumentError("m72_execution_forbidden", self.source_identity)
        object.__setattr__(self, "plan_fingerprint", fingerprint(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema": CONTRACT_CODE,
            "schema_version": CONTRACT_VERSION,
            "tenant_id": self.tenant_id,
            "organization_unit_id": self.organization_unit_id,
            "source_identity": self.source_identity,
            "source_fingerprint": self.source_fingerprint,
            "disposition": self.disposition,
            "disposition_reason": self.disposition_reason,
            "command": self.command.canonical_payload() if self.command else None,
            "writer_routing": "unchanged",
            "execution_allowed": False,
        }


@dataclass(frozen=True)
class FinancialDocumentTarget:
    target_type: str
    target_public_id: UUID

    def __post_init__(self) -> None:
        object.__setattr__(self, "target_type", str(self.target_type).strip().lower())
        object.__setattr__(self, "target_public_id", UUID(str(self.target_public_id)))
        if self.target_type not in {
            "commercial_event", "payment_settlement", "receivable", "refund", "fulfillment_cost"
        }:
            raise WndInventoryDocumentError("unsupported_document_target", self.target_type)
        if self.target_public_id.int == 0:
            raise WndInventoryDocumentError("invalid_document_target", self.target_type)


@dataclass(frozen=True)
class FinancialDocumentLinkagePlan:
    tenant_id: int
    organization_unit_id: int
    source_identity: str
    source_fingerprint: str
    document_type: str
    document_number: str
    issued_at: datetime
    content_hash: str
    targets: tuple[FinancialDocumentTarget, ...]
    original_artifact_preserved: bool = True
    regeneration_allowed: bool = False
    writer_routing: str = "unchanged"
    execution_allowed: bool = False
    plan_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "document_type", str(self.document_type).strip().lower())
        object.__setattr__(self, "document_number", str(self.document_number).strip())
        object.__setattr__(self, "content_hash", require_hash(self.content_hash, "content_hash"))
        object.__setattr__(self, "targets", tuple(self.targets))
        if min(self.tenant_id, self.organization_unit_id) <= 0:
            raise WndInventoryDocumentError("invalid_scope", self.source_identity)
        if self.document_type not in {"receipt", "credit_note", "refund_notice"}:
            raise WndInventoryDocumentError("unsupported_document_type", self.document_type)
        if not self.document_number or len(self.document_number) > 80:
            raise WndInventoryDocumentError("document_number_required", self.source_identity)
        if self.issued_at.tzinfo is None or self.issued_at.utcoffset() is None:
            raise WndInventoryDocumentError("timezone_required", self.document_number)
        if not self.targets or len({(x.target_type, x.target_public_id) for x in self.targets}) != len(self.targets):
            raise WndInventoryDocumentError("document_targets_invalid", self.document_number)
        if not self.original_artifact_preserved or self.regeneration_allowed:
            raise WndInventoryDocumentError("historical_document_rewrite_forbidden", self.document_number)
        if self.writer_routing != "unchanged" or self.execution_allowed:
            raise WndInventoryDocumentError("m72_execution_forbidden", self.document_number)
        object.__setattr__(self, "plan_fingerprint", fingerprint(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema": CONTRACT_CODE,
            "schema_version": CONTRACT_VERSION,
            "tenant_id": self.tenant_id,
            "organization_unit_id": self.organization_unit_id,
            "source_identity": self.source_identity,
            "source_fingerprint": self.source_fingerprint,
            "document_type": self.document_type,
            "document_number": self.document_number,
            "issued_at": self.issued_at,
            "content_hash": self.content_hash,
            "targets": [
                {"target_type": item.target_type, "target_public_id": str(item.target_public_id)}
                for item in self.targets
            ],
            "original_artifact_preserved": True,
            "regeneration_allowed": False,
            "writer_routing": "unchanged",
            "execution_allowed": False,
        }


def assert_inventory_replay(
    existing: InventoryFinancialHandoffPlan, candidate: InventoryFinancialHandoffPlan
) -> InventoryFinancialHandoffPlan:
    if (existing.tenant_id, existing.organization_unit_id, existing.source_identity) != (
        candidate.tenant_id, candidate.organization_unit_id, candidate.source_identity
    ):
        raise WndInventoryDocumentError("replay_identity_mismatch", candidate.source_identity)
    if existing.plan_fingerprint != candidate.plan_fingerprint:
        raise WndInventoryDocumentError("mapping_idempotency_conflict", candidate.source_identity)
    return existing


def assert_document_replay(
    existing: FinancialDocumentLinkagePlan, candidate: FinancialDocumentLinkagePlan
) -> FinancialDocumentLinkagePlan:
    if (existing.tenant_id, existing.organization_unit_id, existing.document_type, existing.document_number) != (
        candidate.tenant_id, candidate.organization_unit_id, candidate.document_type, candidate.document_number
    ):
        raise WndInventoryDocumentError("replay_identity_mismatch", candidate.document_number)
    if existing.plan_fingerprint != candidate.plan_fingerprint:
        raise WndInventoryDocumentError("document_idempotency_conflict", candidate.document_number)
    return existing
