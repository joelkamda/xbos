"""As-of obligation balances and aging from immutable timestamped facts."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from .aging_contract import AgedObligation,AgingSummary,AgingValidationError,AsOfAgingQuery


_AS_OF=text("""
WITH reversal_totals AS (
  SELECT ar.tenant_id,ar.payment_allocation_id,SUM(ar.reversal_amount) reversed_amount
  FROM public.allocation_reversals ar WHERE ar.tenant_id=:tenant AND ar.occurred_at<=:as_of
  GROUP BY ar.tenant_id,ar.payment_allocation_id
), allocation_totals AS (
  SELECT pa.tenant_id,pa.obligation_id,SUM(pa.allocation_amount) allocated_amount,
         SUM(COALESCE(rt.reversed_amount,0)) reversed_amount
  FROM public.payment_allocations pa LEFT JOIN reversal_totals rt
    ON rt.tenant_id=pa.tenant_id AND rt.payment_allocation_id=pa.id
  WHERE pa.tenant_id=:tenant AND pa.occurred_at<=:as_of
  GROUP BY pa.tenant_id,pa.obligation_id
), ranked_states AS (
  SELECT st.*,ROW_NUMBER() OVER (PARTITION BY st.tenant_id,st.obligation_id ORDER BY st.effective_at DESC,st.id DESC) rank
  FROM public.obligation_state_transitions st WHERE st.tenant_id=:tenant AND st.effective_at<=:as_of
)
SELECT o.public_id,o.tenant_id,o.organization_unit_id,o.original_amount,o.currency_code,
       (o.due_at AT TIME ZONE ou.timezone_name)::date due_business_date,
       COALESCE(a.allocated_amount,0) allocated_amount,COALESCE(a.reversed_amount,0) reversed_amount,
       st.to_state state_as_of,st.id state_transition_id
FROM public.financial_obligations o
JOIN public.organization_units ou ON ou.tenant_id=o.tenant_id AND ou.id=o.organization_unit_id
LEFT JOIN allocation_totals a ON a.tenant_id=o.tenant_id AND a.obligation_id=o.id
JOIN ranked_states st ON st.tenant_id=o.tenant_id AND st.obligation_id=o.id AND st.rank=1
WHERE o.tenant_id=:tenant AND o.occurred_at<=:as_of
  AND (:organization_id IS NULL OR o.organization_unit_id=:organization_id)
ORDER BY due_business_date,o.public_id
""")


class ObligationAgingService:
    @staticmethod
    def get(session,query: AsOfAgingQuery) -> AgingSummary:
        rows=session.execute(_AS_OF,{"tenant":query.tenant_id,"as_of":query.as_of,
                                    "organization_id":query.organization_unit_id}).mappings().all()
        aged=[]; totals=defaultdict(lambda:Decimal("0")); currencies=set()
        for row in rows:
            original=Decimal(row.original_amount); allocated=Decimal(row.allocated_amount); reversed_amount=Decimal(row.reversed_amount)
            outstanding=original-allocated+reversed_amount
            if outstanding < 0: raise AgingValidationError("obligation_capacity_corrupt","as-of facts exceed obligation capacity")
            if outstanding == 0: continue
            if not query.include_terminal and row.state_as_of in {"cancelled","written_off"}: continue
            due_date=row.due_business_date
            days=(query.as_of_business_date-due_date).days
            bucket=query.policy.classify(days); totals[bucket]+=outstanding; currencies.add(row.currency_code)
            aged.append(AgedObligation(UUID(str(row.public_id)),row.tenant_id,row.organization_unit_id,original,
              allocated,reversed_amount,outstanding,row.currency_code,due_date,days,bucket,row.state_as_of,int(row.state_transition_id)))
        for bucket in query.policy.buckets: totals[bucket.code]+=Decimal("0")
        return AgingSummary(query.tenant_id,query.as_of,query.as_of_business_date,query.policy.code,query.policy.version,
                            tuple(aged),dict(totals),next(iter(currencies)) if len(currencies)==1 else None)
