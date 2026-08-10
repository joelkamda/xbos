"""Read-only, tenant-scoped obligation statement projection."""
from __future__ import annotations
from decimal import Decimal
from sqlalchemy import bindparam,text
from .statement_contract import FinancialStatementError

class FinancialStatementRepository:
    @staticmethod
    def rows(session,query):
        party_column="o.debtor_party_id" if query.statement_type=="customer" else "o.creditor_party_id"
        types=("trade_receivable","customer_receivable") if query.statement_type=="customer" else ("trade_payable","expense_payable")
        org="AND o.organization_unit_id=:organization" if query.organization_unit_id is not None else ""
        params={"tenant":query.tenant_id,"party":str(query.party_id),"currency":query.currency_code,"start":query.period_start,"end":query.period_end,"as_of":query.as_of,"types":types,"organization":query.organization_unit_id}
        opening=Decimal(session.execute(text(f"""WITH charges AS (SELECT coalesce(sum(original_amount),0) amount FROM financial_obligations o WHERE o.tenant_id=:tenant AND {party_column}=:party AND o.currency_code=:currency AND o.obligation_type IN :types {org} AND o.occurred_at<:start), credits AS (SELECT coalesce(sum(pa.allocation_amount-coalesce(r.amount,0)),0) amount FROM payment_allocations pa JOIN financial_obligations o ON o.id=pa.obligation_id LEFT JOIN (SELECT payment_allocation_id,sum(reversal_amount) amount FROM allocation_reversals WHERE occurred_at<:start GROUP BY payment_allocation_id) r ON r.payment_allocation_id=pa.id WHERE o.tenant_id=:tenant AND {party_column}=:party AND o.currency_code=:currency AND o.obligation_type IN :types {org} AND pa.occurred_at<:start) SELECT charges.amount-credits.amount FROM charges,credits""").bindparams(bindparam("types",expanding=True)),params).scalar_one())
        rows=session.execute(text(f"""SELECT o.occurred_at,1 sequence,'obligation' line_type,o.public_id::text reference,o.original_amount debit,0::numeric credit FROM financial_obligations o WHERE o.tenant_id=:tenant AND {party_column}=:party AND o.currency_code=:currency AND o.obligation_type IN :types {org} AND o.business_date BETWEEN :start AND :end AND o.occurred_at<=:as_of UNION ALL SELECT pa.occurred_at,2,'allocation',pa.public_id::text,0::numeric,pa.allocation_amount-coalesce(r.amount,0) FROM payment_allocations pa JOIN financial_obligations o ON o.id=pa.obligation_id LEFT JOIN (SELECT payment_allocation_id,sum(reversal_amount) amount FROM allocation_reversals WHERE occurred_at<=:as_of GROUP BY payment_allocation_id) r ON r.payment_allocation_id=pa.id WHERE o.tenant_id=:tenant AND {party_column}=:party AND o.currency_code=:currency AND o.obligation_type IN :types {org} AND pa.business_date BETWEEN :start AND :end AND pa.occurred_at<=:as_of ORDER BY occurred_at,sequence,reference""").bindparams(bindparam("types",expanding=True)),params).mappings().all()
        return opening,rows
