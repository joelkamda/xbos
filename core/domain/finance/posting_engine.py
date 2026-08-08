"""Deterministic balanced posting of one immutable financial event."""

from __future__ import annotations

from decimal import Decimal

from .dimension_contract import parse_posting_dimension_context
from .dimension_repository import FinancialDimensionRepository
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
    dimension_repository = FinancialDimensionRepository

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
                dimension_context = parse_posting_dimension_context(
                    event.posting_context
                )
                if (
                    dimension_context.global_values
                    or dimension_context.account_role_values
                ):
                    raise FinancialEventValidationError(
                        "correction_dimensions_immutable",
                        "correction postings inherit the original journal dimensions",
                    )
                lines = cls._inverse_original_lines(session, event)
            else:
                dimension_context = parse_posting_dimension_context(
                    event.posting_context
                )
                dimension_context.assert_roles_allowed(
                    set(profile.debit_roles) | set(profile.credit_roles)
                )
                lines = cls._template_lines(
                    session, event, profile, dimension_context
                )
            cls._validate_balance(lines, event.amount)
            return cls.repository.insert_posted_entry(
                session,
                event,
                profile_code=profile.profile_code,
                period_id=period_id,
                lines=lines,
            )

    @classmethod
    def _template_lines(cls, session, event, profile, dimension_context):
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
                financial_dimensions = cls.dimension_repository.resolve_line_snapshot(
                    session,
                    event,
                    profile_code=profile.profile_code,
                    account_role=account_role,
                    context=dimension_context,
                )
                lines.append(
                    JournalLineDraft(
                        ledger_account_id=binding.ledger_account_id,
                        account_role=account_role,
                        side=side,
                        amount=event.amount,
                        dimension_snapshot={
                            "classification_snapshot": dict(
                                event.classification_snapshot
                            ),
                            "posting_profile_code": profile.profile_code,
                            "financial_dimensions": financial_dimensions,
                        },
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
                    dimension_snapshot=dict(line.dimension_snapshot),
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
