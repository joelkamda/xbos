"""Locked cumulative-capacity policy for original-linked financial corrections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from .event_contract import (
    CanonicalFinancialEventCommand,
    CatalogEventPolicy,
    FinancialEventValidationError,
)


SPECIFIC_REVERSAL_TARGETS = {
    "COMMERCIAL_RETURN_RECOGNIZED": "COMMERCIAL_REVENUE_RECOGNIZED",
    "PAYMENT_SETTLEMENT_REVERSED": "PAYMENT_SETTLED",
    "PAYMENT_ALLOCATION_REVERSED": "PAYMENT_ALLOCATED",
}
GENERIC_REVERSAL_TYPE = "FINANCIAL_FACT_REVERSED"
ORIGINAL_LINKED_TYPES = frozenset((*SPECIFIC_REVERSAL_TARGETS, GENERIC_REVERSAL_TYPE))


@dataclass(frozen=True)
class ReversalCapacity:
    original_event_id: int
    original_public_id: UUID
    original_event_type_code: str
    original_amount: Decimal
    previously_reversed: Decimal
    requested_amount: Decimal
    remaining_before: Decimal
    remaining_after: Decimal


class FinancialEventReversalPolicy:
    """Serialize corrections on the original event and validate remaining value."""

    @staticmethod
    def validate_and_lock(
        session,
        command: CanonicalFinancialEventCommand,
        policy: CatalogEventPolicy,
    ) -> ReversalCapacity | None:
        if command.original_event_id is None:
            return None
        if command.event_type_code not in ORIGINAL_LINKED_TYPES:
            raise FinancialEventValidationError(
                "unsupported_original_link",
                "only approved correction types may reference an original event",
            )

        original = session.execute(
            text(
                """
                SELECT fe.id, fe.public_id, fe.event_type_code, fe.event_version,
                       fe.amount, fe.currency_code, fe.organization_unit_id,
                       fe.source_operational_account_id,
                       fe.target_operational_account_id, fe.original_event_id,
                       fe.occurred_at, fetv.posting_eligible,
                       COALESCE(
                           (fetv.account_role_policy ->> 'requires_original_event')::boolean,
                           FALSE
                       ) AS requires_original_event
                FROM public.financial_events fe
                JOIN public.financial_event_type_versions fetv
                  ON fetv.event_type_code = fe.event_type_code
                 AND fetv.event_version = fe.event_version
                WHERE fe.tenant_id = :tenant_id AND fe.id = :original_event_id
                FOR UPDATE OF fe
                """
            ),
            {
                "tenant_id": command.tenant_id,
                "original_event_id": command.original_event_id,
            },
        ).mappings().one_or_none()
        if original is None:
            raise FinancialEventValidationError(
                "original_event_not_found",
                "original event is missing or belongs to another tenant",
            )
        if original["original_event_id"] is not None or original["requires_original_event"]:
            raise FinancialEventValidationError(
                "original_event_is_correction",
                "a correction cannot itself become the original of another correction",
            )
        if original["organization_unit_id"] != command.organization_unit_id:
            raise FinancialEventValidationError(
                "original_event_organization_mismatch",
                "correction and original must share an organization unit",
            )
        if original["currency_code"] != command.currency_code:
            raise FinancialEventValidationError(
                "original_event_currency_mismatch",
                "correction and original must share a currency",
            )
        if command.occurred_at < original["occurred_at"]:
            raise FinancialEventValidationError(
                "correction_precedes_original",
                "correction occurred_at cannot precede the original event",
            )

        expected = SPECIFIC_REVERSAL_TARGETS.get(command.event_type_code)
        if expected is not None and original["event_type_code"] != expected:
            raise FinancialEventValidationError(
                "reversal_type_mismatch",
                f"{command.event_type_code} requires original type {expected}",
            )
        if command.event_type_code == GENERIC_REVERSAL_TYPE:
            if original["event_type_code"] in set(SPECIFIC_REVERSAL_TARGETS.values()):
                raise FinancialEventValidationError(
                    "specific_reversal_type_required",
                    "the original event has a dedicated correction type",
                )
            if not original["posting_eligible"]:
                raise FinancialEventValidationError(
                    "original_event_not_posting_eligible",
                    "generic reversal requires a posting-eligible original event",
                )

        mode = policy.operational_account_policy.get("mode")
        if mode == "inverse_original":
            if (
                command.source_operational_account_id
                != original["target_operational_account_id"]
                or command.target_operational_account_id
                != original["source_operational_account_id"]
            ):
                raise FinancialEventValidationError(
                    "inverse_original_accounts_mismatch",
                    "correction accounts must exactly invert the original event",
                )

        previously_reversed = Decimal(
            session.execute(
                text(
                    """
                    SELECT COALESCE(sum(amount), 0)
                    FROM public.financial_events
                    WHERE tenant_id = :tenant_id
                      AND original_event_id = :original_event_id
                    """
                ),
                {
                    "tenant_id": command.tenant_id,
                    "original_event_id": command.original_event_id,
                },
            ).scalar_one()
        )
        original_amount = Decimal(original["amount"])
        remaining_before = original_amount - previously_reversed
        if command.amount > remaining_before:
            raise FinancialEventValidationError(
                "reversal_capacity_exceeded",
                "cumulative correction amount exceeds the original event amount",
            )
        return ReversalCapacity(
            original_event_id=original["id"],
            original_public_id=UUID(str(original["public_id"])),
            original_event_type_code=original["event_type_code"],
            original_amount=original_amount,
            previously_reversed=previously_reversed,
            requested_amount=command.amount,
            remaining_before=remaining_before,
            remaining_after=remaining_before - command.amount,
        )
