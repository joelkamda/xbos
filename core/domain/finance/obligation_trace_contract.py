"""Typed read-only contracts for M3.5 obligation settlement traces."""

from __future__ import annotations
from dataclasses import dataclass
from datetime import date,datetime
from typing import Mapping,Any
from uuid import UUID

class ObligationTraceError(RuntimeError):
    def __init__(self,code:str,message:str): super().__init__(message); self.code=code
class ObligationTraceNotFound(ObligationTraceError): pass
class ObligationTraceIntegrityError(ObligationTraceError): pass

@dataclass(frozen=True)
class ObligationTraceQuery:
    tenant_id:int
    obligation_public_id:UUID
    as_of:datetime|None=None
    as_of_business_date:date|None=None
    def __post_init__(self):
        object.__setattr__(self,"obligation_public_id",UUID(str(self.obligation_public_id)))
        if self.tenant_id<=0: raise ObligationTraceError("invalid_tenant","tenant_id must be positive")
        if (self.as_of is None)!=(self.as_of_business_date is None):
            raise ObligationTraceError("incomplete_as_of","as_of timestamp and business date must be paired")
        if self.as_of is not None and (self.as_of.tzinfo is None or self.as_of.utcoffset() is None):
            raise ObligationTraceError("timezone_required","as_of must be timezone-aware")

@dataclass(frozen=True)
class ObligationSettlementTrace:
    query:ObligationTraceQuery
    obligation:Mapping[str,Any]
    lines:tuple[Mapping[str,Any],...]
    state_history:tuple[Mapping[str,Any],...]
    allocations:tuple[Mapping[str,Any],...]
    balance:Mapping[str,Any]
    correlated_financial_events:tuple[Mapping[str,Any],...]
    correlated_journals:tuple[Mapping[str,Any],...]
    integrity:Mapping[str,Any]
    explanation:Mapping[str,str]
