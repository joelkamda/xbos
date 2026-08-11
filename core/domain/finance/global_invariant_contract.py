"""Pure exact-decimal contract for M8 global financial invariant probes."""
from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable


class GlobalInvariantError(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _decimal(value: object, field: str) -> Decimal:
    try:
        selected = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise GlobalInvariantError("invalid_decimal", field) from exc
    if not selected.is_finite():
        raise GlobalInvariantError("invalid_decimal", field)
    return selected


def _canonical(value: Decimal) -> str:
    if value == 0:
        return "0"
    rendered = format(value.normalize(), "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


@dataclass(frozen=True)
class FinancialInvariantCase:
    case_id: str
    obligation_amount: Decimal
    allocation_amounts: tuple[Decimal, ...]
    allocation_reversals: tuple[Decimal, ...]
    settlement_amount: Decimal
    settlement_reversals: tuple[Decimal, ...]
    journal_debits: tuple[Decimal, ...]
    journal_credits: tuple[Decimal, ...]
    transfer_source_delta: Decimal
    transfer_destination_delta: Decimal

    def __post_init__(self) -> None:
        if not str(self.case_id).strip():
            raise GlobalInvariantError("case_id_required", "case_id")
        for name in (
            "obligation_amount", "settlement_amount", "transfer_source_delta",
            "transfer_destination_delta",
        ):
            object.__setattr__(self, name, _decimal(getattr(self, name), name))
        for name in (
            "allocation_amounts", "allocation_reversals", "settlement_reversals",
            "journal_debits", "journal_credits",
        ):
            object.__setattr__(
                self, name, tuple(_decimal(value, name) for value in getattr(self, name))
            )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "obligation_amount": _canonical(self.obligation_amount),
            "allocation_amounts": [_canonical(v) for v in self.allocation_amounts],
            "allocation_reversals": [_canonical(v) for v in self.allocation_reversals],
            "settlement_amount": _canonical(self.settlement_amount),
            "settlement_reversals": [_canonical(v) for v in self.settlement_reversals],
            "journal_debits": [_canonical(v) for v in self.journal_debits],
            "journal_credits": [_canonical(v) for v in self.journal_credits],
            "transfer_source_delta": _canonical(self.transfer_source_delta),
            "transfer_destination_delta": _canonical(self.transfer_destination_delta),
        }

    @property
    def fingerprint(self) -> str:
        encoded = json.dumps(
            self.canonical_payload(), sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def validate_global_invariants(case: FinancialInvariantCase) -> None:
    nonnegative = (
        ("obligation_amount", (case.obligation_amount,)),
        ("allocation_amount", case.allocation_amounts),
        ("allocation_reversal", case.allocation_reversals),
        ("settlement_amount", (case.settlement_amount,)),
        ("settlement_reversal", case.settlement_reversals),
        ("journal_debit", case.journal_debits),
        ("journal_credit", case.journal_credits),
    )
    for label, values in nonnegative:
        if any(value < 0 for value in values):
            raise GlobalInvariantError("negative_financial_amount", label)
    allocations = sum(case.allocation_amounts, Decimal("0"))
    allocation_reversals = sum(case.allocation_reversals, Decimal("0"))
    if allocations > case.obligation_amount:
        raise GlobalInvariantError("obligation_capacity_exceeded", case.case_id)
    if allocation_reversals > allocations:
        raise GlobalInvariantError("allocation_reversal_capacity_exceeded", case.case_id)
    if sum(case.settlement_reversals, Decimal("0")) > case.settlement_amount:
        raise GlobalInvariantError("settlement_reversal_capacity_exceeded", case.case_id)
    if sum(case.journal_debits, Decimal("0")) != sum(case.journal_credits, Decimal("0")):
        raise GlobalInvariantError("journal_unbalanced", case.case_id)
    if case.transfer_source_delta > 0 or case.transfer_destination_delta < 0:
        raise GlobalInvariantError("transfer_direction_invalid", case.case_id)
    if case.transfer_source_delta + case.transfer_destination_delta != 0:
        raise GlobalInvariantError("transfer_value_not_conserved", case.case_id)


def deterministic_property_cases(*, seed: int = 8000, count: int = 512) -> tuple[FinancialInvariantCase, ...]:
    if count < 1 or count > 10000 or not isinstance(seed, int):
        raise GlobalInvariantError("invalid_property_corpus", f"seed={seed}; count={count}")
    generator = random.Random(seed)
    cases: list[FinancialInvariantCase] = []
    boundaries = (0, 1, 2, 10, 100, 99999999)
    for index in range(count):
        obligation_units = boundaries[index % len(boundaries)] if index < len(boundaries) else generator.randrange(0, 10**8)
        allocated_units = generator.randrange(0, obligation_units + 1) if obligation_units else 0
        reversed_units = generator.randrange(0, allocated_units + 1) if allocated_units else 0
        settlement_units = boundaries[(index + 2) % len(boundaries)] if index < len(boundaries) else generator.randrange(0, 10**8)
        settlement_reversed = generator.randrange(0, settlement_units + 1) if settlement_units else 0
        journal_total = generator.randrange(0, 10**8)
        debit_a = generator.randrange(0, journal_total + 1) if journal_total else 0
        credit_a = generator.randrange(0, journal_total + 1) if journal_total else 0
        transfer = generator.randrange(0, 10**8)
        cases.append(FinancialInvariantCase(
            case_id=f"m80-{seed}-{index:05d}",
            obligation_amount=Decimal(obligation_units),
            allocation_amounts=(Decimal(allocated_units),),
            allocation_reversals=(Decimal(reversed_units),),
            settlement_amount=Decimal(settlement_units),
            settlement_reversals=(Decimal(settlement_reversed),),
            journal_debits=(Decimal(debit_a), Decimal(journal_total - debit_a)),
            journal_credits=(Decimal(credit_a), Decimal(journal_total - credit_a)),
            transfer_source_delta=Decimal(-transfer),
            transfer_destination_delta=Decimal(transfer),
        ))
    if len({case.fingerprint for case in cases}) != len(cases):
        raise GlobalInvariantError("property_corpus_collision", str(count))
    return tuple(cases)


def validate_property_corpus(cases: Iterable[FinancialInvariantCase]) -> int:
    count = 0
    for case in cases:
        validate_global_invariants(case)
        count += 1
    return count
