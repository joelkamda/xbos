"""Persistence primitives for M3.2 value sources, allocations, and reversals."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from .allocation_contract import AllocationValidationError


@dataclass(frozen=True)
class AllocationFact:
    id: int
    public_id: UUID
    tenant_id: int
    organization_unit_id: int
    amount: Decimal
    currency_code: str
    value_source_public_id: UUID | None = None
    obligation_public_id: UUID | None = None
    payment_allocation_public_id: UUID | None = None
    replayed: bool = False


class AllocationRepository:
    @staticmethod
    def lock_value_source(session, tenant_id: int, public_id: UUID):
        row = session.execute(text("""
            SELECT id, public_id, organization_unit_id, source_amount, currency_code
            FROM public.value_sources WHERE tenant_id=:tenant AND public_id=:public_id FOR UPDATE
        """), {"tenant": tenant_id, "public_id": str(public_id)}).mappings().one_or_none()
        if row is None:
            raise AllocationValidationError("value_source_not_found", "value source does not exist for tenant")
        return row

    @staticmethod
    def lock_obligation(session, tenant_id: int, public_id: UUID):
        row = session.execute(text("""
            SELECT id, public_id, organization_unit_id, original_amount, currency_code, obligation_state
            FROM public.financial_obligations WHERE tenant_id=:tenant AND public_id=:public_id FOR UPDATE
        """), {"tenant": tenant_id, "public_id": str(public_id)}).mappings().one_or_none()
        if row is None:
            raise AllocationValidationError("obligation_not_found", "obligation does not exist for tenant")
        return row

    @staticmethod
    def source_available(session, tenant_id: int, source_id: int) -> Decimal:
        return Decimal(session.execute(text("""
            SELECT vs.source_amount - COALESCE(SUM(pa.allocation_amount - COALESCE(r.reversed,0)),0)
            FROM public.value_sources vs
            LEFT JOIN public.payment_allocations pa ON pa.tenant_id=vs.tenant_id AND pa.value_source_id=vs.id
            LEFT JOIN (SELECT tenant_id,payment_allocation_id,SUM(reversal_amount) reversed
                       FROM public.allocation_reversals GROUP BY tenant_id,payment_allocation_id) r
              ON r.tenant_id=pa.tenant_id AND r.payment_allocation_id=pa.id
            WHERE vs.tenant_id=:tenant AND vs.id=:source_id GROUP BY vs.id
        """), {"tenant": tenant_id, "source_id": source_id}).scalar_one())

    @staticmethod
    def obligation_outstanding(session, tenant_id: int, obligation_id: int) -> Decimal:
        return Decimal(session.execute(text("""
            SELECT o.original_amount - COALESCE(SUM(pa.allocation_amount - COALESCE(r.reversed,0)),0)
            FROM public.financial_obligations o
            LEFT JOIN public.payment_allocations pa ON pa.tenant_id=o.tenant_id AND pa.obligation_id=o.id
            LEFT JOIN (SELECT tenant_id,payment_allocation_id,SUM(reversal_amount) reversed
                       FROM public.allocation_reversals GROUP BY tenant_id,payment_allocation_id) r
              ON r.tenant_id=pa.tenant_id AND r.payment_allocation_id=pa.id
            WHERE o.tenant_id=:tenant AND o.id=:obligation_id GROUP BY o.id
        """), {"tenant": tenant_id, "obligation_id": obligation_id}).scalar_one())

    @staticmethod
    def insert_value_source(session, command) -> AllocationFact:
        row = session.execute(text("""
            INSERT INTO public.value_sources (
              public_id,tenant_id,organization_unit_id,owner_party_id,source_type,source_amount,currency_code,
              payment_settlement_public_id,occurred_at,business_date,calendar_policy_version,correlation_id,
              actor_user_id,actor_service,source_component,source_record_id,idempotency_scope,idempotency_key,
              request_fingerprint,metadata)
            VALUES (:public_id,:tenant_id,:organization_unit_id,:owner_party_id,:source_type,:source_amount,:currency_code,
              :payment_settlement_public_id,:occurred_at,:business_date,:calendar_policy_version,:correlation_id,
              :actor_user_id,:actor_service,:source_component,:source_record_id,:idempotency_scope,:idempotency_key,
              :request_fingerprint,CAST(:metadata AS JSONB))
            RETURNING id,public_id,tenant_id,organization_unit_id,source_amount,currency_code
        """), {**command.canonical_payload(), "owner_party_id": str(command.owner_party_id),
                 "payment_settlement_public_id": str(command.payment_settlement_public_id) if command.payment_settlement_public_id else None,
                 "source_amount": command.source_amount, "request_fingerprint": command.request_fingerprint,
                 "metadata": json.dumps(command.metadata, sort_keys=True)}).mappings().one()
        return AllocationFact(int(row.id), UUID(str(row.public_id)), row.tenant_id, row.organization_unit_id,
                              Decimal(row.source_amount), row.currency_code)

    @staticmethod
    def insert_allocation(session, command, source, obligation) -> AllocationFact:
        row = session.execute(text("""
            INSERT INTO public.payment_allocations (
              public_id,tenant_id,organization_unit_id,value_source_id,obligation_id,allocation_amount,currency_code,
              occurred_at,business_date,calendar_policy_version,correlation_id,actor_user_id,actor_service,
              source_component,source_record_id,idempotency_scope,idempotency_key,request_fingerprint,
              cross_organization_policy_code,cross_organization_policy_version,metadata)
            VALUES (:public_id,:tenant_id,:organization_unit_id,:value_source_id,:obligation_id,:allocation_amount,:currency_code,
              :occurred_at,:business_date,:calendar_policy_version,:correlation_id,:actor_user_id,:actor_service,
              :source_component,:source_record_id,:idempotency_scope,:idempotency_key,:request_fingerprint,
              :cross_organization_policy_code,:cross_organization_policy_version,CAST(:metadata AS JSONB))
            RETURNING id,public_id,tenant_id,organization_unit_id,allocation_amount,currency_code
        """), {**command.canonical_payload(), "value_source_id": source["id"], "obligation_id": obligation["id"],
                 "allocation_amount": command.allocation_amount, "request_fingerprint": command.request_fingerprint,
                 "metadata": json.dumps(command.metadata, sort_keys=True)}).mappings().one()
        return AllocationFact(int(row.id), UUID(str(row.public_id)), row.tenant_id, row.organization_unit_id,
                              Decimal(row.allocation_amount), row.currency_code,
                              UUID(str(source["public_id"])), UUID(str(obligation["public_id"])))

    @staticmethod
    def get_allocation(session, tenant_id: int, public_id: UUID, *, lock: bool = False):
        suffix = " FOR UPDATE OF pa" if lock else ""
        row = session.execute(text("""
            SELECT pa.id,pa.public_id,pa.organization_unit_id,pa.allocation_amount,pa.currency_code,
                   vs.public_id value_source_public_id,o.public_id obligation_public_id,
                   pa.value_source_id,pa.obligation_id
            FROM public.payment_allocations pa
            JOIN public.value_sources vs ON vs.tenant_id=pa.tenant_id AND vs.id=pa.value_source_id
            JOIN public.financial_obligations o ON o.tenant_id=pa.tenant_id AND o.id=pa.obligation_id
            WHERE pa.tenant_id=:tenant AND pa.public_id=:public_id
        """ + suffix), {"tenant": tenant_id, "public_id": str(public_id)}).mappings().one_or_none()
        if row is None:
            raise AllocationValidationError("allocation_not_found", "allocation does not exist for tenant")
        return row

    @staticmethod
    def reversed_amount(session, tenant_id: int, allocation_id: int) -> Decimal:
        return Decimal(session.execute(text("""
            SELECT COALESCE(SUM(reversal_amount),0) FROM public.allocation_reversals
            WHERE tenant_id=:tenant AND payment_allocation_id=:allocation_id
        """), {"tenant": tenant_id, "allocation_id": allocation_id}).scalar_one())

    @staticmethod
    def insert_reversal(session, command, allocation) -> AllocationFact:
        row = session.execute(text("""
            INSERT INTO public.allocation_reversals (
              public_id,tenant_id,organization_unit_id,payment_allocation_id,reversal_amount,currency_code,reason_code,
              occurred_at,business_date,calendar_policy_version,correlation_id,actor_user_id,actor_service,
              source_component,source_record_id,idempotency_scope,idempotency_key,request_fingerprint,metadata)
            VALUES (:public_id,:tenant_id,:organization_unit_id,:payment_allocation_id,:reversal_amount,:currency_code,:reason_code,
              :occurred_at,:business_date,:calendar_policy_version,:correlation_id,:actor_user_id,:actor_service,
              :source_component,:source_record_id,:idempotency_scope,:idempotency_key,:request_fingerprint,CAST(:metadata AS JSONB))
            RETURNING id,public_id,tenant_id,organization_unit_id,reversal_amount,currency_code
        """), {**command.canonical_payload(), "payment_allocation_id": allocation["id"],
                 "reversal_amount": command.reversal_amount, "request_fingerprint": command.request_fingerprint,
                 "metadata": json.dumps(command.metadata, sort_keys=True)}).mappings().one()
        return AllocationFact(int(row.id), UUID(str(row.public_id)), row.tenant_id, row.organization_unit_id,
                              Decimal(row.reversal_amount), row.currency_code,
                              UUID(str(allocation["value_source_public_id"])), UUID(str(allocation["obligation_public_id"])),
                              UUID(str(allocation["public_id"])))

    @staticmethod
    def find_fact(session, table: str, tenant_id: int, public_id: UUID) -> AllocationFact | None:
        columns = {"value_sources": "source_amount", "payment_allocations": "allocation_amount",
                   "allocation_reversals": "reversal_amount"}
        if table not in columns:
            raise ValueError("unapproved fact table")
        row = session.execute(text(f"SELECT id,public_id,tenant_id,organization_unit_id,{columns[table]} amount,currency_code FROM public.{table} WHERE tenant_id=:tenant AND public_id=:public_id"),
                              {"tenant": tenant_id, "public_id": str(public_id)}).mappings().one_or_none()
        return None if row is None else AllocationFact(int(row.id), UUID(str(row.public_id)), row.tenant_id,
                                                        row.organization_unit_id, Decimal(row.amount), row.currency_code,
                                                        replayed=True)
