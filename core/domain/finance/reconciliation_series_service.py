"""Read-only deterministic M6.1 reconciliation history."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping
from uuid import UUID

from .operational_transfer_contract import ReconciliationSeriesQuery, OperationalTransferValidationError
from .operational_transfer_repository import OperationalTransferRepository


@dataclass(frozen=True)
class ReconciliationSeriesEntry:
    sequence: int
    fact_kind: str
    fact_public_id: UUID
    original_fact_public_id: UUID | None
    fact_at: object
    value_at: object
    recorded_at: object
    direction: str
    amount: Decimal
    effect_amount: Decimal | None
    balance_snapshot: Decimal | None
    currency_code: str
    provenance: str
    evidence_hash: str | None
    correlation_id: UUID
    causation_id: UUID | None
    source_reference: str
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class ReconciliationSeries:
    tenant_id: int
    organization_unit_id: int
    operational_account_public_id: UUID
    from_at: object | None
    through_at: object
    entries: tuple[ReconciliationSeriesEntry, ...]


class ReconciliationSeriesService:
    repository = OperationalTransferRepository

    @classmethod
    def resolve(cls, session, query: ReconciliationSeriesQuery) -> ReconciliationSeries:
        from .operational_balance_repository import OperationalBalanceRepository
        account = OperationalBalanceRepository.account_by_public_id(
            session, tenant_id=query.tenant_id, public_id=query.operational_account_public_id
        )
        if account is None:
            raise OperationalTransferValidationError("account_not_found", "operational account is missing or cross-tenant")
        if account.organization_unit_id != query.organization_unit_id:
            raise OperationalTransferValidationError("account_organization_mismatch", "operational account organization differs")
        rows = cls.repository.series_rows(
            session, tenant_id=query.tenant_id, organization_unit_id=query.organization_unit_id,
            account_id=account.id, from_at=query.from_at, through_at=query.through_at,
        )
        entries = tuple(ReconciliationSeriesEntry(
            sequence=index, fact_kind=row["fact_kind"], fact_public_id=UUID(str(row["fact_public_id"])),
            original_fact_public_id=UUID(str(row["original_fact_public_id"])) if row["original_fact_public_id"] else None,
            fact_at=row["fact_at"], value_at=row["value_at"], recorded_at=row["recorded_at"],
            direction=row["direction"], amount=Decimal(row["amount"]),
            effect_amount=Decimal(row["effect_amount"]) if row["effect_amount"] is not None else None,
            balance_snapshot=Decimal(row["balance_snapshot"]) if row["balance_snapshot"] is not None else None,
            currency_code=row["currency_code"], provenance=row["provenance"],
            evidence_hash=row["evidence_hash"].strip() if row["evidence_hash"] else None,
            correlation_id=UUID(str(row["correlation_id"])),
            causation_id=UUID(str(row["causation_id"])) if row["causation_id"] else None,
            source_reference=row["source_reference"], metadata=dict(row["metadata"]),
        ) for index, row in enumerate(rows, 1))
        return ReconciliationSeries(
            query.tenant_id, query.organization_unit_id, query.operational_account_public_id,
            query.from_at, query.through_at, entries,
        )
