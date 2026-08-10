"""Typed deterministic customer and supplier statement contracts for M5.5."""
from __future__ import annotations
import hashlib,json,re
from dataclasses import dataclass
from datetime import date,datetime,timezone
from decimal import Decimal
from uuid import UUID

_CURRENCY=re.compile(r"^[A-Z]{3}$")
class FinancialStatementError(RuntimeError):
    def __init__(self,code,message):super().__init__(message);self.code=code

@dataclass(frozen=True)
class FinancialStatementQuery:
    tenant_id:int; organization_unit_id:int|None; party_id:UUID; statement_type:str; currency_code:str; period_start:date; period_end:date; as_of:datetime
    def __post_init__(self):
        object.__setattr__(self,"party_id",UUID(str(self.party_id)));object.__setattr__(self,"statement_type",str(self.statement_type).strip().lower());object.__setattr__(self,"currency_code",str(self.currency_code).strip().upper())
        if self.tenant_id<=0 or (self.organization_unit_id is not None and self.organization_unit_id<=0):raise FinancialStatementError("invalid_scope","tenant and optional organization must be positive")
        if self.statement_type not in {"customer","supplier"}:raise FinancialStatementError("invalid_statement_type","statement type must be customer or supplier")
        if not _CURRENCY.fullmatch(self.currency_code):raise FinancialStatementError("invalid_currency","currency must be three uppercase letters")
        if self.period_end<self.period_start:raise FinancialStatementError("invalid_period","statement end cannot precede start")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:raise FinancialStatementError("timezone_required","as_of must be timezone-aware")
        if self.as_of.date()<self.period_end:raise FinancialStatementError("as_of_precedes_period","as_of cannot precede statement end")

@dataclass(frozen=True)
class FinancialStatementLine:
    occurred_at:datetime; sequence:int; line_type:str; reference:str; debit:Decimal; credit:Decimal; running_balance:Decimal

@dataclass(frozen=True)
class FinancialStatement:
    query:FinancialStatementQuery; opening_balance:Decimal; total_debits:Decimal; total_credits:Decimal; closing_balance:Decimal; lines:tuple[FinancialStatementLine,...]; semantic_sha256:str

def statement_digest(query,opening,rows):
    payload={"tenant_id":query.tenant_id,"organization_unit_id":query.organization_unit_id,"party_id":str(query.party_id),"statement_type":query.statement_type,"currency_code":query.currency_code,"period_start":query.period_start.isoformat(),"period_end":query.period_end.isoformat(),"as_of":query.as_of.astimezone(timezone.utc).isoformat().replace("+00:00","Z"),"opening":str(opening),"rows":[[r["occurred_at"].astimezone(timezone.utc).isoformat().replace("+00:00","Z"),r["sequence"],r["line_type"],r["reference"],str(r["debit"]),str(r["credit"])] for r in rows]}
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
