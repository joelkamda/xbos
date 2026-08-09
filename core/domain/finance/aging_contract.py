"""Pure contracts for deterministic obligation aging."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID


class AgingValidationError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message); self.code=code


@dataclass(frozen=True)
class AgingBucket:
    code: str
    lower_days: int | None
    upper_days: int | None

    def contains(self, days: int) -> bool:
        return (self.lower_days is None or days >= self.lower_days) and (self.upper_days is None or days <= self.upper_days)


DEFAULT_BUCKETS=(
    AgingBucket("not_due",None,-1), AgingBucket("due_today",0,0), AgingBucket("past_due_1_30",1,30),
    AgingBucket("past_due_31_60",31,60), AgingBucket("past_due_61_90",61,90), AgingBucket("past_due_91_plus",91,None),
)


@dataclass(frozen=True)
class AgingPolicy:
    code: str="standard_receivables"
    version: int=1
    buckets: tuple[AgingBucket,...]=DEFAULT_BUCKETS

    def __post_init__(self):
        if self.version <= 0 or not self.code: raise AgingValidationError("invalid_policy","aging policy identity is invalid")
        probes=range(-2,367)
        if any(sum(bucket.contains(day) for bucket in self.buckets)!=1 for day in probes):
            raise AgingValidationError("invalid_buckets","aging buckets must cover days exactly once")

    def classify(self, days: int) -> str:
        for bucket in self.buckets:
            if bucket.contains(days): return bucket.code
        raise AgingValidationError("unclassified_age","aging policy does not classify the value")


@dataclass(frozen=True)
class AsOfAgingQuery:
    tenant_id: int
    as_of: datetime
    as_of_business_date: date
    organization_unit_id: int | None=None
    include_terminal: bool=False
    policy: AgingPolicy=AgingPolicy()

    def __post_init__(self):
        if self.tenant_id <= 0 or (self.organization_unit_id is not None and self.organization_unit_id <= 0):
            raise AgingValidationError("invalid_scope","tenant and organization scope must be positive")
        if not isinstance(self.as_of,datetime) or self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise AgingValidationError("timezone_required","as_of must be timezone-aware")


@dataclass(frozen=True)
class AgedObligation:
    obligation_public_id: UUID
    tenant_id: int
    organization_unit_id: int
    original_amount: Decimal
    allocated_amount: Decimal
    reversed_amount: Decimal
    outstanding_amount: Decimal
    currency_code: str
    due_business_date: date
    days_past_due: int
    bucket_code: str
    state_as_of: str
    state_transition_id: int


@dataclass(frozen=True)
class AgingSummary:
    tenant_id: int
    as_of: datetime
    as_of_business_date: date
    policy_code: str
    policy_version: int
    rows: tuple[AgedObligation,...]
    bucket_totals: dict[str,Decimal]
    currency_code: str | None
