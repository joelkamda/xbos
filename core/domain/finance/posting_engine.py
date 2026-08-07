"""Deterministic balanced posting of one immutable financial event."""

from __future__ import annotations

from decimal import Decimal

from .event_contract import FinancialEventValidationError
from .event_repository import FinancialEventRecord
from .posting_contract import binding_key_for, select_posting_profile
from .posting_repository import (
    CanonicalPostingRepository,
    JournalEntryRecord,
    JournalLineDraft,
)


class CanonicalFinancialPostingEngine:
    repository = CanonicalPostingRepository

    @classmethod
    def post(
        cls, session, event: FinancialEventRecord
    ) -> JournalEntryRecord | None:
        with session.begin_nested():
            cls.repository.lock_event(session, event)
            existing = cls.repository.find_for_event(session, event, replayed=True)
            if existing is not None:
                return existing

            profile = select_posting_profile(
                event.event_type_code, event.posting_context
            )
            if profile is None:
                return None
            if event.amount <= 0:
                raise FinancialEventValidationError(
                    "posting_amount_not_positive",
                    "M2.4 journal posting requires a positive event amount",
                )
            if event.posting_context.get("base_currency_code", event.currency_code) != event.currency_code:
                raise FinancialEventValidationError(
                    "fx_posting_deferred",
                    "M2.4 accepts same-currency posting only; FX posting is deferred",
                )

            period_id = cls.repository.resolve_open_period(session, event)
            if profile.mode == "inverse_original":
                lines = cls._inverse_original_lines(session, event)
            else:
                lines = cls._template_lines(session, event, profile)
            cls._validate_balance(lines, event.amount)
            return cls.repository.insert_posted_entry(
                session,
                event,
                profile_code=profile.profile_code,
                period_id=period_id,
                lines=lines,
            )

    @classmethod
    def _template_lines(cls, session, event, profile):
        lines: list[JournalLineDraft] = []
        for side, roles in (
            ("debit", profile.debit_roles),
            ("credit", profile.credit_roles),
        ):
            for account_role in roles:
                binding = cls.repository.resolve_account_binding(
                    session,
                    event,
                    account_role,
                    binding_key_for(event.posting_context, account_role),
                )
                lines.append(
                    JournalLineDraft(
                        ledger_account_id=binding.ledger_account_id,
                        account_role=account_role,
                        side=side,
                        amount=event.amount,
                    )
                )
        return tuple(lines)

    @classmethod
    def _inverse_original_lines(cls, session, event):
        original_lines = cls.repository.load_original_posting_lines(session, event)
        drafts: list[JournalLineDraft] = []
        for line in original_lines:
            original_side = (
                "debit" if line.transaction_debit_amount > 0 else "credit"
            )
            drafts.append(
                JournalLineDraft(
                    ledger_account_id=line.ledger_account_id,
                    account_role=line.account_role,
                    side="credit" if original_side == "debit" else "debit",
                    amount=event.amount,
                )
            )
        return tuple(drafts)

    @staticmethod
    def _validate_balance(lines, event_amount: Decimal) -> None:
        if len(lines) < 2:
            raise FinancialEventValidationError(
                "journal_too_few_lines", "posted journal requires at least two lines"
            )
        debit = sum(
            (line.amount for line in lines if line.side == "debit"), Decimal("0")
        )
        credit = sum(
            (line.amount for line in lines if line.side == "credit"), Decimal("0")
        )
        if debit != credit:
            raise FinancialEventValidationError(
                "journal_not_balanced", "posting profile did not produce a balanced journal"
            )
        if debit != event_amount:
            raise FinancialEventValidationError(
                "journal_amount_mismatch",
                "M2.4 two-line posting total must equal the event amount",
            )
