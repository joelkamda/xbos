"""Deterministic, read-only explanation of obligation settlement evidence."""

from __future__ import annotations
from decimal import Decimal
from .obligation_trace_contract import ObligationSettlementTrace,ObligationTraceIntegrityError,ObligationTraceNotFound
from .obligation_trace_repository import ObligationTraceRepository

class ObligationSettlementTraceService:
    repository=ObligationTraceRepository
    @classmethod
    def explain(cls,session,query):
        obligation=cls.repository.obligation(session,query)
        if obligation is None: raise ObligationTraceNotFound("obligation_not_found","obligation was not found in authorized tenant scope at cutoff")
        lines=cls.repository.lines(session,query.tenant_id,obligation["id"])
        states=cls.repository.states(session,query.tenant_id,obligation["id"],query.as_of,query.as_of_business_date)
        allocations=cls.repository.allocations(session,query.tenant_id,obligation["id"],query.as_of,query.as_of_business_date)
        if not states: raise ObligationTraceIntegrityError("state_history_missing","obligation has no state authority at cutoff")
        allocated=sum((Decimal(row["allocation_amount"]) for row in allocations),Decimal("0"))
        reversed_amount=sum((Decimal(row["reversed_amount"]) for row in allocations),Decimal("0"))
        original=Decimal(obligation["original_amount"]); active=allocated-reversed_amount; outstanding=original-active
        if active<0 or outstanding<0: raise ObligationTraceIntegrityError("capacity_corrupt","settlement facts exceed governed capacity")
        events=cls.repository.correlated_events(session,query.tenant_id,obligation["correlation_id"],query.as_of,query.as_of_business_date)
        journals=cls.repository.correlated_journals(session,query.tenant_id,obligation["correlation_id"],query.as_of,query.as_of_business_date)
        checks={"tenant_scope":int(obligation["tenant_id"])==query.tenant_id,
          "line_total":sum((Decimal(row["line_amount"]) for row in lines),Decimal("0"))==original,
          "state_history_present":bool(states),"nonnegative_active_satisfaction":active>=0,
          "nonnegative_outstanding":outstanding>=0,
          "allocation_reversals_within_originals":all(Decimal(r["reversed_amount"])<=Decimal(r["allocation_amount"]) for r in allocations),
          "correlated_journals_balanced":all(Decimal(j["transaction_debits"])==Decimal(j["transaction_credits"]) for j in journals)}
        integrity={"status":"PASS" if all(checks.values()) else "FAIL","checks":checks}
        public_obligation={k:v for k,v in dict(obligation).items() if k not in {"id","tenant_id"}}
        public_allocations=tuple({k:v for k,v in dict(row).items() if k!="id"} for row in allocations)
        public_events=tuple({k:v for k,v in dict(row).items() if k!="id"} for row in events)
        public_journals=tuple({k:v for k,v in dict(row).items() if k!="id"} for row in journals)
        balance={"original_amount":original,"allocated_amount":allocated,"reversed_amount":reversed_amount,
          "active_satisfaction":active,"outstanding_amount":outstanding,"currency_code":obligation["currency_code"],
          "state_as_of":states[-1]["to_state"],"as_of":query.as_of,
          "as_of_business_date":query.as_of_business_date}
        explanation={"what_is_owed":f"{outstanding} {obligation['currency_code']} remains from {original}.",
          "how_value_was_applied":f"{len(allocations)} allocation fact(s) applied {allocated}; reversals reopened {reversed_amount}.",
          "lifecycle":f"State at cutoff is {states[-1]['to_state']} from {len(states)} append-only transition fact(s).",
          "ledger_evidence":f"{len(events)} financial event(s) and {len(journals)} journal(s) share the correlation identity; correlation is evidence, not asserted causation.",
          "authority":"Immutable obligation, allocation, reversal, lifecycle, event, and journal facts are authoritative; this trace is derived and read-only."}
        return ObligationSettlementTrace(query,public_obligation,tuple(map(dict,lines)),tuple({k:v for k,v in dict(r).items() if k!="id"} for r in states),
          public_allocations,balance,public_events,public_journals,integrity,explanation)
