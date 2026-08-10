"""Deterministic customer and supplier statement assembly."""
from __future__ import annotations
from decimal import Decimal
from .statement_contract import FinancialStatement,FinancialStatementLine,statement_digest
from .statement_repository import FinancialStatementRepository

class FinancialStatementService:
    repository=FinancialStatementRepository
    @classmethod
    def generate(cls,session,query):
        opening,rows=cls.repository.rows(session,query);balance=Decimal(opening);lines=[];debits=Decimal("0");credits=Decimal("0")
        for row in rows:
            debit=Decimal(row["debit"]);credit=Decimal(row["credit"]);debits+=debit;credits+=credit;balance+=debit-credit
            lines.append(FinancialStatementLine(row["occurred_at"],int(row["sequence"]),row["line_type"],row["reference"],debit,credit,balance))
        return FinancialStatement(query,Decimal(opening),debits,credits,balance,tuple(lines),statement_digest(query,opening,rows))
