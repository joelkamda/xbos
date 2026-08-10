"""Persistence support for M6.1 transfers and explanatory reconciliation series."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from .operational_balance_repository import OperationalAccountRecord, _account


@dataclass(frozen=True)
class OriginalTransferRecord:
    id: int
    public_id: UUID
    tenant_id: int
    organization_unit_id: int
    source_operational_account_id: int
    target_operational_account_id: int
    amount: Decimal
    currency_code: str
    occurred_at: object


class OperationalTransferRepository:
    @staticmethod
    def lock_transfer_by_idempotency(session, *, tenant_id: int, idempotency_scope: str, idempotency_key: str) -> OriginalTransferRecord | None:
        row = session.execute(text("""
            SELECT id,public_id,tenant_id,organization_unit_id,source_operational_account_id,
                   target_operational_account_id,amount,currency_code,occurred_at
            FROM public.financial_events
            WHERE tenant_id=:tenant AND idempotency_scope=:scope AND idempotency_key=:key
              AND event_type_code='VALUE_TRANSFERRED'
            FOR UPDATE
        """), {"tenant": tenant_id, "scope": idempotency_scope, "key": idempotency_key}).mappings().one_or_none()
        return OperationalTransferRepository._original(row) if row else None

    @staticmethod
    def lock_accounts(session, *, tenant_id: int, source_public_id: UUID, destination_public_id: UUID) -> tuple[OperationalAccountRecord, OperationalAccountRecord]:
        rows = session.execute(text("""
            SELECT a.id,a.public_id,a.tenant_id,a.organization_unit_id,a.parent_account_id,
                   a.account_class,a.account_type,a.code,a.display_name,a.currency_code,a.aggregation_role,
                   a.reconciliation_enabled,a.active,a.opened_at,a.closed_at
            FROM public.operational_financial_accounts a
            WHERE a.tenant_id=:tenant AND a.public_id IN (:source,:destination)
            ORDER BY a.id
            FOR UPDATE OF a
        """), {"tenant": tenant_id, "source": str(source_public_id), "destination": str(destination_public_id)}).mappings().all()
        by_public = {UUID(str(row["public_id"])): _account(row) for row in rows}
        source = by_public.get(source_public_id)
        destination = by_public.get(destination_public_id)
        if source is None or destination is None:
            from .operational_transfer_contract import OperationalTransferValidationError
            raise OperationalTransferValidationError("operational_account_not_found", "source or destination account is missing or cross-tenant")
        return source, destination

    @staticmethod
    def lock_original_transfer(session, *, tenant_id: int, public_id: UUID) -> OriginalTransferRecord | None:
        row = session.execute(text("""
            SELECT id,public_id,tenant_id,organization_unit_id,source_operational_account_id,
                   target_operational_account_id,amount,currency_code,occurred_at
            FROM public.financial_events
            WHERE tenant_id=:tenant AND public_id=:public AND event_type_code='VALUE_TRANSFERRED'
            FOR UPDATE
        """), {"tenant": tenant_id, "public": str(public_id)}).mappings().one_or_none()
        return OperationalTransferRepository._original(row) if row else None

    @staticmethod
    def _original(row) -> OriginalTransferRecord:
        return OriginalTransferRecord(
            int(row["id"]), UUID(str(row["public_id"])), int(row["tenant_id"]),
            int(row["organization_unit_id"]), int(row["source_operational_account_id"]),
            int(row["target_operational_account_id"]), Decimal(row["amount"]),
            row["currency_code"], row["occurred_at"],
        )

    @staticmethod
    def account_by_id(session, *, tenant_id: int, account_id: int) -> OperationalAccountRecord | None:
        row = session.execute(text("""
            SELECT a.id,a.public_id,a.tenant_id,a.organization_unit_id,a.parent_account_id,
                   a.account_class,a.account_type,a.code,a.display_name,a.currency_code,a.aggregation_role,
                   a.reconciliation_enabled,a.active,a.opened_at,a.closed_at
            FROM public.operational_financial_accounts a
            WHERE a.tenant_id=:tenant AND a.id=:account
        """), {"tenant": tenant_id, "account": account_id}).mappings().one_or_none()
        return _account(row) if row else None

    @staticmethod
    def series_rows(session, *, tenant_id: int, organization_unit_id: int, account_id: int, from_at, through_at):
        return session.execute(text("""
            SELECT fact_kind,fact_public_id,original_fact_public_id,fact_at,value_at,recorded_at,
                   direction,amount,effect_amount,balance_snapshot,currency_code,provenance,
                   evidence_hash,correlation_id,causation_id,source_reference,metadata
            FROM public.operational_account_reconciliation_series
            WHERE tenant_id=:tenant AND organization_unit_id=:org AND operational_account_id=:account
              AND fact_at<=:through_at AND (:from_at IS NULL OR fact_at>=:from_at)
            ORDER BY fact_at,sort_rank,recorded_at,fact_public_id,direction
        """), {
            "tenant": tenant_id, "org": organization_unit_id, "account": account_id,
            "from_at": from_at, "through_at": through_at,
        }).mappings().all()
