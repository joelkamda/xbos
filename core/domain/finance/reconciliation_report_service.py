"""Deterministic read-only M6.4 reconciliation reports."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from .operational_balance_contract import _fingerprint
from .reconciliation_control_contract import ReconciliationControlError
from .reconciliation_control_repository import ReconciliationControlRepository
from .trace_contract import json_value


def _canonical_report_payload(record, explanations, evidence):
    """Return the exact JSON-safe value hashed for a report revision."""

    return json_value({
        "public_id": record.public_id, "control_type": record.control_type,
        "tenant_id": record.tenant_id, "organization_unit_id": record.organization_unit_id,
        "currency_code": record.currency_code, "canonical_opening": record.canonical_opening,
        "canonical_increases": record.canonical_increases, "canonical_decreases": record.canonical_decreases,
        "canonical_adjustments": record.canonical_adjustments, "canonical_closing": record.canonical_closing,
        "control_position": record.control_position, "explained_amount": record.explained_amount,
        "unexplained_variance": record.unexplained_variance, "status": record.reconciliation_status,
        "revision_number": record.revision_number, "explanations": explanations,
        "evidence": evidence, "semantic_fingerprint": record.semantic_fingerprint,
    })


@dataclass(frozen=True)
class ReconciliationReport:
    public_id: UUID
    control_type: str
    tenant_id: int
    organization_unit_id: int
    currency_code: str
    canonical_opening: Decimal
    canonical_increases: Decimal
    canonical_decreases: Decimal
    canonical_adjustments: Decimal
    canonical_closing: Decimal
    control_position: Decimal
    explained_amount: Decimal
    unexplained_variance: Decimal
    status: str
    revision_number: int
    explanations: tuple[dict, ...]
    evidence: tuple[dict, ...]
    semantic_fingerprint: str
    report_fingerprint: str


class ReconciliationReportService:
    repository = ReconciliationControlRepository

    @classmethod
    def render(cls, session, *, tenant_id: int, public_id: UUID):
        record = cls.repository.by_public_id(session, tenant_id, public_id)
        if record is None:
            raise ReconciliationControlError("reconciliation_not_found", "reconciliation control is absent or cross-tenant")
        items, evidence = cls.repository.report_rows(session, tenant_id, record.id)
        item_values = tuple(dict(row) for row in items)
        evidence_values = tuple(dict(row) for row in evidence)
        payload = _canonical_report_payload(record, item_values, evidence_values)
        return ReconciliationReport(
            record.public_id, record.control_type, record.tenant_id, record.organization_unit_id,
            record.currency_code, record.canonical_opening, record.canonical_increases,
            record.canonical_decreases, record.canonical_adjustments, record.canonical_closing,
            record.control_position, record.explained_amount, record.unexplained_variance,
            record.reconciliation_status, record.revision_number, item_values, evidence_values,
            record.semantic_fingerprint, _fingerprint(payload),
        )
