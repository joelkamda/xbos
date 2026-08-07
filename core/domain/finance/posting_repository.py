"""Persistence for deterministic, balanced, event-linked journals."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Mapping, Sequence
from uuid import UUID

from sqlalchemy import text

from .event_contract import FinancialEventValidationError
from .event_repository import FinancialEventRecord
from .posting_contract import ACCOUNT_ROLE_POLICIES


@dataclass(frozen=True)
class LedgerAccountBinding:
    ledger_account_id: int
    account_role: str
    account_type: str
    normal_balance: str
    operational_account_id: int | None


@dataclass(frozen=True)
class JournalLineDraft:
    ledger_account_id: int
    account_role: str
    side: str
    amount: Decimal


@dataclass(frozen=True)
class JournalLineRecord:
    id: int
    line_number: int
    ledger_account_id: int
    account_role: str
    transaction_debit_amount: Decimal
    transaction_credit_amount: Decimal
    base_debit_amount: Decimal
    base_credit_amount: Decimal


@dataclass(frozen=True)
class JournalEntryRecord:
    id: int
    public_id: UUID
    tenant_id: int
    legal_entity_unit_id: int
    accounting_period_id: int
    journal_code: str
    entry_number: str
    entry_state: str
    transaction_currency_code: str
    base_currency_code: str
    posting_date: date
    business_date: date
    posting_profile_code: str
    correlation_id: UUID
    posted_at: datetime | None
    lines: tuple[JournalLineRecord, ...] = ()
    replayed: bool = False


_ENTRY_COLUMNS = """
    id, public_id, tenant_id, legal_entity_unit_id, accounting_period_id,
    journal_code, entry_number, entry_state, transaction_currency_code,
    base_currency_code, posting_date, business_date, posting_profile_code,
    correlation_id, posted_at
"""

_ENTRY_SELECT_COLUMNS = """
    je.id AS id, je.public_id AS public_id, je.tenant_id AS tenant_id,
    je.legal_entity_unit_id AS legal_entity_unit_id,
    je.accounting_period_id AS accounting_period_id,
    je.journal_code AS journal_code, je.entry_number AS entry_number,
    je.entry_state AS entry_state,
    je.transaction_currency_code AS transaction_currency_code,
    je.base_currency_code AS base_currency_code,
    je.posting_date AS posting_date, je.business_date AS business_date,
    je.posting_profile_code AS posting_profile_code,
    je.correlation_id AS correlation_id, je.posted_at AS posted_at
"""

_LINE_COLUMNS = """
    id, line_number, ledger_account_id, account_role,
    transaction_debit_amount, transaction_credit_amount,
    base_debit_amount, base_credit_amount
"""


class CanonicalPostingRepository:
    @staticmethod
    def lock_event(session, event: FinancialEventRecord) -> None:
        locked = session.execute(
            text(
                """
                SELECT id
                FROM public.financial_events
                WHERE tenant_id = :tenant_id AND id = :event_id
                FOR UPDATE
                """
            ),
            {"tenant_id": event.tenant_id, "event_id": event.id},
        ).scalar_one_or_none()
        if locked is None:
            raise FinancialEventValidationError(
                "posting_event_missing", "authoritative financial event does not exist"
            )

    @classmethod
    def find_for_event(
        cls, session, event: FinancialEventRecord, *, replayed: bool = False
    ) -> JournalEntryRecord | None:
        rows = session.execute(
            text(
                f"""
                SELECT {_ENTRY_SELECT_COLUMNS}
                FROM public.journal_entries je
                JOIN public.journal_entry_event_links link
                  ON link.tenant_id = je.tenant_id
                 AND link.journal_entry_id = je.id
                WHERE link.tenant_id = :tenant_id
                  AND link.financial_event_id = :event_id
                  AND link.allocation_role = 'primary_event_posting'
                ORDER BY je.id
                LIMIT 2
                """
            ),
            {"tenant_id": event.tenant_id, "event_id": event.id},
        ).mappings().all()
        if not rows:
            return None
        if len(rows) != 1:
            raise FinancialEventValidationError(
                "primary_posting_ambiguous",
                "financial event has multiple authoritative primary journals",
            )
        row = rows[0]
        return cls._entry_from_row(session, row, replayed=replayed)

    @classmethod
    def _entry_from_row(cls, session, row, *, replayed: bool) -> JournalEntryRecord:
        lines = session.execute(
            text(
                f"""
                SELECT {_LINE_COLUMNS}
                FROM public.journal_lines
                WHERE tenant_id = :tenant_id AND journal_entry_id = :entry_id
                ORDER BY line_number
                """
            ),
            {"tenant_id": row["tenant_id"], "entry_id": row["id"]},
        ).mappings().all()
        return JournalEntryRecord(
            id=int(row["id"]),
            public_id=UUID(str(row["public_id"])),
            tenant_id=int(row["tenant_id"]),
            legal_entity_unit_id=int(row["legal_entity_unit_id"]),
            accounting_period_id=int(row["accounting_period_id"]),
            journal_code=row["journal_code"],
            entry_number=row["entry_number"],
            entry_state=row["entry_state"],
            transaction_currency_code=row["transaction_currency_code"],
            base_currency_code=row["base_currency_code"],
            posting_date=row["posting_date"],
            business_date=row["business_date"],
            posting_profile_code=row["posting_profile_code"],
            correlation_id=UUID(str(row["correlation_id"])),
            posted_at=row["posted_at"],
            lines=tuple(cls._line_from_row(line) for line in lines),
            replayed=replayed,
        )

    @staticmethod
    def _line_from_row(row) -> JournalLineRecord:
        return JournalLineRecord(
            id=int(row["id"]),
            line_number=int(row["line_number"]),
            ledger_account_id=int(row["ledger_account_id"]),
            account_role=row["account_role"],
            transaction_debit_amount=row["transaction_debit_amount"],
            transaction_credit_amount=row["transaction_credit_amount"],
            base_debit_amount=row["base_debit_amount"],
            base_credit_amount=row["base_credit_amount"],
        )

    @staticmethod
    def resolve_open_period(session, event: FinancialEventRecord) -> int:
        rows = session.execute(
            text(
                """
                SELECT id
                FROM public.accounting_periods
                WHERE tenant_id = :tenant_id
                  AND legal_entity_unit_id = :organization_unit_id
                  AND period_state IN ('open','reopened')
                  AND period_start <= :business_date
                  AND period_end >= :business_date
                ORDER BY period_start DESC, id DESC
                FOR SHARE
                """
            ),
            {
                "tenant_id": event.tenant_id,
                "organization_unit_id": event.organization_unit_id,
                "business_date": event.business_date,
            },
        ).scalars().all()
        if not rows:
            raise FinancialEventValidationError(
                "accounting_period_not_open",
                "no open accounting period covers the event business date",
            )
        if len(rows) != 1:
            raise FinancialEventValidationError(
                "accounting_period_ambiguous",
                "more than one open accounting period covers the event business date",
            )
        return int(rows[0])

    @staticmethod
    def resolve_account_binding(
        session,
        event: FinancialEventRecord,
        account_role: str,
        binding_key: str,
    ) -> LedgerAccountBinding:
        rows = session.execute(
            text(
                """
                SELECT binding.ledger_account_id,
                       binding.account_role,
                       binding.operational_account_id,
                       account.account_type,
                       account.normal_balance,
                       account.currency_policy,
                       account.fixed_currency_code
                FROM public.ledger_account_role_bindings binding
                JOIN public.ledger_accounts account
                  ON account.tenant_id = binding.tenant_id
                 AND account.id = binding.ledger_account_id
                WHERE binding.tenant_id = :tenant_id
                  AND binding.legal_entity_unit_id = :organization_unit_id
                  AND binding.account_role = :account_role
                  AND binding.binding_key = :binding_key
                  AND binding.currency_code = :currency_code
                  AND binding.active
                  AND account.active
                  AND binding.effective_from <= :business_date
                  AND (binding.effective_to IS NULL OR binding.effective_to >= :business_date)
                  AND account.effective_from <= :business_date
                  AND (account.effective_to IS NULL OR account.effective_to >= :business_date)
                ORDER BY binding.effective_from DESC, binding.id DESC
                LIMIT 2
                FOR SHARE OF binding, account
                """
            ),
            {
                "tenant_id": event.tenant_id,
                "organization_unit_id": event.organization_unit_id,
                "account_role": account_role,
                "binding_key": binding_key,
                "currency_code": event.currency_code,
                "business_date": event.business_date,
            },
        ).mappings().all()
        if not rows:
            raise FinancialEventValidationError(
                "account_role_unbound",
                f"no effective ledger binding exists for account role {account_role}",
            )
        if len(rows) != 1:
            raise FinancialEventValidationError(
                "account_role_binding_ambiguous",
                f"multiple effective ledger bindings exist for account role {account_role}",
            )
        row = rows[0]
        allowed_types, allowed_balances, operational_policy = ACCOUNT_ROLE_POLICIES[
            account_role
        ]
        if row["account_type"] not in allowed_types:
            raise FinancialEventValidationError(
                "account_role_type_mismatch",
                f"ledger account type is not allowed for account role {account_role}",
            )
        if row["normal_balance"] not in allowed_balances:
            raise FinancialEventValidationError(
                "account_role_balance_mismatch",
                f"ledger account normal balance is not allowed for account role {account_role}",
            )
        if row["currency_policy"] == "fixed" and row["fixed_currency_code"] != event.currency_code:
            raise FinancialEventValidationError(
                "account_currency_mismatch",
                "fixed-currency ledger account does not match the event currency",
            )
        operational_id = row["operational_account_id"]
        allowed_operational_ids = {
            value
            for value in (
                event.source_operational_account_id,
                event.target_operational_account_id,
            )
            if value is not None
        }
        if operational_policy == "forbidden" and operational_id is not None:
            raise FinancialEventValidationError(
                "operational_link_forbidden",
                f"account role {account_role} cannot bind an operational account",
            )
        if operational_policy == "required" and operational_id not in allowed_operational_ids:
            raise FinancialEventValidationError(
                "operational_link_required",
                f"account role {account_role} must bind an event operational account",
            )
        if operational_policy == "optional" and operational_id is not None and operational_id not in allowed_operational_ids:
            raise FinancialEventValidationError(
                "operational_link_mismatch",
                f"account role {account_role} binds an unrelated operational account",
            )
        return LedgerAccountBinding(
            ledger_account_id=int(row["ledger_account_id"]),
            account_role=account_role,
            account_type=row["account_type"],
            normal_balance=row["normal_balance"],
            operational_account_id=operational_id,
        )

    @classmethod
    def load_original_posting_lines(
        cls, session, event: FinancialEventRecord
    ) -> tuple[JournalLineRecord, ...]:
        if event.original_event_id is None:
            raise FinancialEventValidationError(
                "original_event_required", "inverse posting requires original_event_id"
            )
        original = session.execute(
            text(
                """
                SELECT id, amount, currency_code
                FROM public.financial_events
                WHERE tenant_id = :tenant_id AND id = :original_event_id
                FOR UPDATE
                """
            ),
            {
                "tenant_id": event.tenant_id,
                "original_event_id": event.original_event_id,
            },
        ).mappings().one_or_none()
        if original is None:
            raise FinancialEventValidationError(
                "original_event_missing", "original financial event does not exist"
            )
        rows = session.execute(
            text(
                """
                SELECT je.id, je.entry_state
                FROM public.journal_entries je
                JOIN public.journal_entry_event_links link
                  ON link.tenant_id = je.tenant_id
                 AND link.journal_entry_id = je.id
                WHERE link.tenant_id = :tenant_id
                  AND link.financial_event_id = :original_event_id
                  AND link.allocation_role = 'primary_event_posting'
                ORDER BY je.id
                LIMIT 2
                FOR SHARE OF je
                """
            ),
            {
                "tenant_id": event.tenant_id,
                "original_event_id": event.original_event_id,
            },
        ).mappings().all()
        if not rows or rows[0]["entry_state"] != "posted":
            raise FinancialEventValidationError(
                "original_posting_missing",
                "original event has no authoritative posted journal",
            )
        if len(rows) != 1:
            raise FinancialEventValidationError(
                "original_posting_ambiguous",
                "original event has multiple authoritative primary journals",
            )
        row = rows[0]
        lines = session.execute(
            text(
                f"""
                SELECT {_LINE_COLUMNS}
                FROM public.journal_lines
                WHERE tenant_id = :tenant_id AND journal_entry_id = :entry_id
                ORDER BY line_number
                """
            ),
            {"tenant_id": event.tenant_id, "entry_id": row["id"]},
        ).mappings().all()
        if len(lines) != 2:
            raise FinancialEventValidationError(
                "inverse_original_shape_unsupported",
                "M2.4 inverse posting requires the original two-line template shape",
            )
        return tuple(cls._line_from_row(line) for line in lines)

    @classmethod
    def insert_posted_entry(
        cls,
        session,
        event: FinancialEventRecord,
        *,
        profile_code: str,
        period_id: int,
        lines: Sequence[JournalLineDraft],
    ) -> JournalEntryRecord:
        entry = session.execute(
            text(
                f"""
                INSERT INTO public.journal_entries (
                    tenant_id, legal_entity_unit_id, accounting_period_id,
                    journal_code, entry_number, entry_state,
                    transaction_currency_code, base_currency_code,
                    posting_date, business_date, description,
                    posting_profile_code, created_by_user_id, created_by_service,
                    correlation_id, metadata
                ) VALUES (
                    :tenant_id, :organization_unit_id, :period_id,
                    'FIN', :entry_number, 'draft',
                    :currency_code, :currency_code,
                    :business_date, :business_date, :description,
                    :profile_code, :actor_user_id, :actor_service,
                    :correlation_id, CAST(:metadata AS JSONB)
                )
                RETURNING {_ENTRY_COLUMNS}
                """
            ),
            {
                "tenant_id": event.tenant_id,
                "organization_unit_id": event.organization_unit_id,
                "period_id": period_id,
                "entry_number": f"FE-{event.public_id}",
                "currency_code": event.currency_code,
                "business_date": event.business_date,
                "description": f"{event.event_type_code} {event.public_id}",
                "profile_code": profile_code,
                "actor_user_id": event.actor_user_id,
                "actor_service": event.actor_service or "xbos.finance.posting.v1",
                "correlation_id": str(event.correlation_id),
                "metadata": json.dumps(
                    {
                        "contract": "XBOS_M24_CANONICAL_BALANCED_POSTING",
                        "contract_version": 1,
                        "financial_event_public_id": str(event.public_id),
                    },
                    sort_keys=True,
                ),
            },
        ).mappings().one()

        for line_number, line in enumerate(lines, start=1):
            debit = line.amount if line.side == "debit" else Decimal("0")
            credit = line.amount if line.side == "credit" else Decimal("0")
            session.execute(
                text(
                    """
                    INSERT INTO public.journal_lines (
                        tenant_id, journal_entry_id, line_number,
                        ledger_account_id, account_role, description,
                        transaction_currency_code,
                        transaction_debit_amount, transaction_credit_amount,
                        base_currency_code, base_debit_amount, base_credit_amount,
                        fx_rate, organization_unit_id, source_record_id,
                        dimension_snapshot
                    ) VALUES (
                        :tenant_id, :entry_id, :line_number,
                        :ledger_account_id, :account_role, :description,
                        :currency_code, :debit, :credit,
                        :currency_code, :debit, :credit,
                        1, :organization_unit_id, :source_record_id,
                        CAST(:dimension_snapshot AS JSONB)
                    )
                    """
                ),
                {
                    "tenant_id": event.tenant_id,
                    "entry_id": entry["id"],
                    "line_number": line_number,
                    "ledger_account_id": line.ledger_account_id,
                    "account_role": line.account_role,
                    "description": event.event_type_code,
                    "currency_code": event.currency_code,
                    "debit": debit,
                    "credit": credit,
                    "organization_unit_id": event.organization_unit_id,
                    "source_record_id": event.source_record_id,
                    "dimension_snapshot": json.dumps(
                        {
                            "classification_snapshot": dict(event.classification_snapshot),
                            "posting_profile_code": profile_code,
                        },
                        sort_keys=True,
                    ),
                },
            )

        session.execute(
            text(
                """
                INSERT INTO public.journal_entry_event_links (
                    tenant_id, journal_entry_id, financial_event_id,
                    source_amount, allocation_role
                ) VALUES (
                    :tenant_id, :entry_id, :event_id,
                    :source_amount, 'primary_event_posting'
                )
                """
            ),
            {
                "tenant_id": event.tenant_id,
                "entry_id": entry["id"],
                "event_id": event.id,
                "source_amount": event.amount,
            },
        )
        posted = session.execute(
            text(
                f"""
                UPDATE public.journal_entries
                SET entry_state = 'posted', posted_at = now(), row_version = row_version + 1
                WHERE tenant_id = :tenant_id AND id = :entry_id
                RETURNING {_ENTRY_COLUMNS}
                """
            ),
            {"tenant_id": event.tenant_id, "entry_id": entry["id"]},
        ).mappings().one()
        return cls._entry_from_row(session, posted, replayed=False)
