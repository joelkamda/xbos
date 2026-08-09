"""Tenant-scoped evidence loading for obligation settlement traces."""

from sqlalchemy import text

class ObligationTraceRepository:
    @staticmethod
    def obligation(session,q):
        return session.execute(text("""SELECT o.id,o.public_id,o.tenant_id,o.organization_unit_id,o.debtor_party_id,o.creditor_party_id,
          o.obligation_type,o.original_amount,o.currency_code,o.due_at,o.occurred_at,o.business_date,o.correlation_id,
          o.source_component,o.source_record_id,o.obligation_state,o.row_version
          FROM financial_obligations o WHERE o.tenant_id=:tenant AND o.public_id=:public_id
          AND (:as_of IS NULL OR o.occurred_at<=:as_of)
          AND (:business_date IS NULL OR o.business_date<=:business_date)"""),{"tenant":q.tenant_id,"public_id":str(q.obligation_public_id),"as_of":q.as_of,"business_date":q.as_of_business_date}).mappings().one_or_none()
    @staticmethod
    def lines(session,tenant,obligation_id):
        return session.execute(text("""SELECT line_number,line_type,description_snapshot,quantity,unit_amount,line_amount,currency_code,
          occurred_at,business_date,source_component,source_record_id,metadata FROM financial_obligation_lines
          WHERE tenant_id=:tenant AND obligation_id=:id ORDER BY line_number"""),{"tenant":tenant,"id":obligation_id}).mappings().all()
    @staticmethod
    def states(session,tenant,obligation_id,as_of,business_date):
        return session.execute(text("""SELECT id,from_state,to_state,transition_kind,effective_at,recorded_at
          FROM obligation_state_transitions WHERE tenant_id=:tenant AND obligation_id=:id
          AND (:as_of IS NULL OR effective_at<=:as_of)
          AND (:business_date IS NULL OR effective_at::date<=:business_date)
          ORDER BY effective_at,id"""),{"tenant":tenant,"id":obligation_id,"as_of":as_of,"business_date":business_date}).mappings().all()
    @staticmethod
    def allocations(session,tenant,obligation_id,as_of,business_date):
        return session.execute(text("""WITH reversals AS (
          SELECT tenant_id,payment_allocation_id,SUM(reversal_amount) reversed_amount,
                 jsonb_agg(jsonb_build_object('public_id',public_id,'amount',reversal_amount,'reason_code',reason_code,
                   'occurred_at',occurred_at,'source_component',source_component,'source_record_id',source_record_id) ORDER BY occurred_at,id) reversal_facts
          FROM allocation_reversals WHERE tenant_id=:tenant AND (:as_of IS NULL OR occurred_at<=:as_of)
          AND (:business_date IS NULL OR business_date<=:business_date)
          GROUP BY tenant_id,payment_allocation_id)
        SELECT pa.id,pa.public_id,pa.allocation_amount,pa.currency_code,pa.occurred_at,pa.business_date,
          pa.source_component,pa.source_record_id,pa.cross_organization_policy_code,pa.cross_organization_policy_version,
          vs.public_id value_source_public_id,vs.source_type,vs.source_amount,vs.organization_unit_id source_organization_unit_id,
          COALESCE(r.reversed_amount,0) reversed_amount,COALESCE(r.reversal_facts,'[]'::jsonb) reversal_facts
        FROM payment_allocations pa JOIN value_sources vs ON vs.tenant_id=pa.tenant_id AND vs.id=pa.value_source_id
        LEFT JOIN reversals r ON r.tenant_id=pa.tenant_id AND r.payment_allocation_id=pa.id
        WHERE pa.tenant_id=:tenant AND pa.obligation_id=:id AND (:as_of IS NULL OR pa.occurred_at<=:as_of)
        AND (:business_date IS NULL OR pa.business_date<=:business_date)
        ORDER BY pa.occurred_at,pa.id"""),{"tenant":tenant,"id":obligation_id,"as_of":as_of,"business_date":business_date}).mappings().all()
    @staticmethod
    def correlated_events(session,tenant,correlation_id,as_of,business_date):
        return session.execute(text("""SELECT id,public_id,event_type_code,event_version,amount,currency_code,business_date,occurred_at
          FROM financial_events WHERE tenant_id=:tenant AND correlation_id=:correlation
          AND (:as_of IS NULL OR occurred_at<=:as_of)
          AND (:business_date IS NULL OR business_date<=:business_date)
          ORDER BY occurred_at,id"""),{"tenant":tenant,"correlation":correlation_id,"as_of":as_of,"business_date":business_date}).mappings().all()
    @staticmethod
    def correlated_journals(session,tenant,correlation_id,as_of,business_date):
        return session.execute(text("""SELECT je.id,je.public_id,je.journal_code,je.entry_number,je.entry_state,
          je.posting_profile_code,je.transaction_currency_code,je.business_date,je.posting_date,
          je.created_at,je.posted_at,COUNT(jl.id) line_count,
          COALESCE(SUM(jl.transaction_debit_amount),0) transaction_debits,
          COALESCE(SUM(jl.transaction_credit_amount),0) transaction_credits
          FROM journal_entries je LEFT JOIN journal_lines jl ON jl.tenant_id=je.tenant_id AND jl.journal_entry_id=je.id
          WHERE je.tenant_id=:tenant AND je.correlation_id=:correlation
          AND (:as_of IS NULL OR COALESCE(je.posted_at,je.created_at)<=:as_of)
          AND (:business_date IS NULL OR je.business_date<=:business_date)
          GROUP BY je.id ORDER BY COALESCE(je.posted_at,je.created_at),je.id"""),{"tenant":tenant,"correlation":correlation_id,"as_of":as_of,"business_date":business_date}).mappings().all()
