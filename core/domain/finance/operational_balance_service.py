"""Deterministic expected, actual, and variance projection for M6.0."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from .operational_balance_contract import OperationalBalanceQuery, OperationalBalanceValidationError
from .operational_balance_repository import OperationalBalanceRepository


@dataclass(frozen=True)
class OperationalBalancePosition:
    operational_account_public_id: UUID
    tenant_id: int
    organization_unit_id: int
    currency_code: str
    as_of: object
    anchor_public_id: UUID
    anchor_balance: Decimal
    anchor_at: object
    anchor_provenance: str
    inflows: Decimal
    outflows: Decimal
    expected_balance: Decimal
    actual_public_id: UUID | None
    actual_balance: Decimal | None
    observed_at: object | None
    actual_provenance: str | None
    variance: Decimal | None


class OperationalBalanceService:
    repository = OperationalBalanceRepository

    @classmethod
    def resolve(cls, session, query: OperationalBalanceQuery) -> OperationalBalancePosition:
        account = cls.repository.account_by_public_id(
            session, tenant_id=query.tenant_id, public_id=query.operational_account_public_id
        )
        if account is None:
            raise OperationalBalanceValidationError("account_not_found", "operational account does not exist in tenant scope")
        if account.organization_unit_id != query.organization_unit_id:
            raise OperationalBalanceValidationError("account_scope_mismatch", "account organization differs")
        if account.aggregation_role != "leaf":
            raise OperationalBalanceValidationError("leaf_account_required", "balance projection requires a leaf account")
        row = cls.repository.position(
            session, tenant_id=query.tenant_id, organization_unit_id=query.organization_unit_id,
            account_id=account.id, as_of=query.as_of,
        )
        if row is None:
            raise OperationalBalanceValidationError("balance_anchor_required", "no opening anchor exists at the requested cutoff")
        return OperationalBalancePosition(
            account.public_id, query.tenant_id, query.organization_unit_id, account.currency_code, query.as_of,
            UUID(str(row["anchor_public_id"])), Decimal(row["anchor_balance"]), row["anchor_at"], row["anchor_provenance"],
            Decimal(row["inflows"]), Decimal(row["outflows"]), Decimal(row["expected_balance"]),
            UUID(str(row["actual_public_id"])) if row["actual_public_id"] else None,
            Decimal(row["actual_balance"]) if row["actual_balance"] is not None else None,
            row["observed_at"], row["actual_provenance"], Decimal(row["variance"]) if row["variance"] is not None else None,
        )
