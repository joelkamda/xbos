"""SQL persistence for governed M4.3 payment settlements."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Mapping
from uuid import UUID

from sqlalchemy import text

from .payment_settlement_contract import (
    CreatePaymentSettlementCommand,
    ReversePaymentSettlementCommand,
    TransitionPaymentSettlementCommand,
)


@dataclass(frozen=True)
class SettlementIntentAuthority:
    id: int
    public_id: UUID
    tenant_id: int
    organization_unit_id: int
    intent_state: str
    requested_amount: Decimal
    currency_code: str
    payment_method_policy: Mapping[str, Any]


@dataclass(frozen=True)
class SettlementAttemptAuthority:
    id: int
    public_id: UUID
    payment_intent_id: int
    payment_tender_id: int | None
    organization_unit_id: int
    attempt_state: str
    attempted_amount: Decimal
    currency_code: str
    payment_method_code: str
    payment_rail_code: str
    external_attempt_reference: str | None


@dataclass(frozen=True)
class PaymentSettlementRecord:
    id: int
    public_id: UUID
    tenant_id: int
    organization_unit_id: int
    payment_intent_id: int
    payment_attempt_id: int | None
    payment_tender_id: int | None
    operational_account_id: int
    settlement_state: str
    settlement_direction: str
    gross_amount: Decimal
    fee_amount: Decimal
    net_amount: Decimal
    reversed_amount: Decimal
    currency_code: str
    payment_method_code: str
    payment_rail_code: str
    finality_status: str
    availability_state: str
    external_settlement_reference: str | None
    value_date: date
    terminal_at: datetime | None
    failure_code: str | None
    evidence_payload: Mapping[str, Any]
    occurred_at: datetime
    recorded_at: datetime
    row_version: int
    replayed: bool = False


@dataclass(frozen=True)
class PaymentSettlementTransitionRecord:
    id: int
    public_id: UUID
    tenant_id: int
    organization_unit_id: int
    payment_settlement_id: int
    sequence_number: int
    from_state: str | None
    to_state: str
    reason_code: str
    finality_status: str
    availability_state: str
    failure_code: str | None
    external_settlement_reference_snapshot: str | None
    value_date_snapshot: date
    evidence_payload: Mapping[str, Any]
    occurred_at: datetime


@dataclass(frozen=True)
class PaymentSettlementReversalRecord:
    id: int
    public_id: UUID
    tenant_id: int
    organization_unit_id: int
    payment_settlement_id: int
    reversal_amount: Decimal
    currency_code: str
    reason_code: str
    occurred_at: datetime
    replayed: bool = False


_SETTLEMENT_COLUMNS = """
 id, public_id, tenant_id, organization_unit_id, payment_intent_id,
 payment_attempt_id, payment_tender_id, operational_account_id, settlement_state,
 settlement_direction, gross_amount, fee_amount, net_amount, reversed_amount,
 currency_code, payment_method_code, payment_rail_code, finality_status,
 availability_state, external_settlement_reference, value_date, terminal_at,
 failure_code, evidence_payload, occurred_at, recorded_at, row_version
"""
_TRANSITION_COLUMNS = """
 id, public_id, tenant_id, organization_unit_id, payment_settlement_id,
 sequence_number, from_state, to_state, reason_code, finality_status,
 availability_state, failure_code, external_settlement_reference_snapshot,
 value_date_snapshot, evidence_payload, occurred_at
"""
_REVERSAL_COLUMNS = """
 id, public_id, tenant_id, organization_unit_id, payment_settlement_id,
 reversal_amount, currency_code, reason_code, occurred_at
"""


def _settlement(row, *, replayed=False):
    values = dict(row); values["public_id"] = UUID(str(values["public_id"]))
    for name in ("gross_amount", "fee_amount", "net_amount", "reversed_amount"):
        values[name] = Decimal(values[name])
    return PaymentSettlementRecord(**values, replayed=replayed)


def _transition(row):
    values = dict(row); values["public_id"] = UUID(str(values["public_id"]))
    return PaymentSettlementTransitionRecord(**values)


def _reversal(row, *, replayed=False):
    values = dict(row); values["public_id"] = UUID(str(values["public_id"])); values["reversal_amount"] = Decimal(values["reversal_amount"])
    return PaymentSettlementReversalRecord(**values, replayed=replayed)


class PaymentSettlementRepository:
    @staticmethod
    def committed_amount(session, *, tenant_id: int, payment_intent_id: int) -> Decimal:
        value = session.execute(text("""
            SELECT COALESCE(sum(gross_amount),0) FROM public.payment_settlements
            WHERE tenant_id=:tenant_id AND payment_intent_id=:intent_id
              AND settlement_state NOT IN ('failed','reversed')
        """), {"tenant_id": tenant_id, "intent_id": payment_intent_id}).scalar_one()
        return Decimal(value)

    @staticmethod
    def lock_intent(session, *, tenant_id: int, public_id: UUID):
        row = session.execute(text("""
            SELECT id, public_id, tenant_id, organization_unit_id, intent_state,
                   requested_amount, currency_code, payment_method_policy
            FROM public.canonical_payment_intents
            WHERE tenant_id=:tenant_id AND public_id=:public_id FOR UPDATE
        """), {"tenant_id": tenant_id, "public_id": str(public_id)}).mappings().one_or_none()
        if not row: return None
        values = dict(row); values["public_id"] = UUID(str(values["public_id"])); values["requested_amount"] = Decimal(values["requested_amount"])
        return SettlementIntentAuthority(**values)

    @staticmethod
    def lock_attempt(session, *, tenant_id: int, public_id: UUID):
        row = session.execute(text("""
            SELECT id, public_id, payment_intent_id, payment_tender_id, organization_unit_id,
                   attempt_state, attempted_amount, currency_code,
                   payment_method_code, payment_rail_code, external_attempt_reference
            FROM public.canonical_payment_attempts
            WHERE tenant_id=:tenant_id AND public_id=:public_id FOR UPDATE
        """), {"tenant_id": tenant_id, "public_id": str(public_id)}).mappings().one_or_none()
        if not row: return None
        values = dict(row); values["public_id"] = UUID(str(values["public_id"])); values["attempted_amount"] = Decimal(values["attempted_amount"])
        return SettlementAttemptAuthority(**values)

    @staticmethod
    def operational_account(session, *, tenant_id: int, public_id: UUID):
        return session.execute(text("""
            SELECT id, tenant_id, organization_unit_id, currency_code, active,
                   aggregation_role, account_class, account_type
            FROM public.operational_financial_accounts
            WHERE tenant_id=:tenant_id AND public_id=:public_id FOR SHARE
        """), {"tenant_id": tenant_id, "public_id": str(public_id)}).mappings().one_or_none()

    @staticmethod
    def callback_event(session, *, tenant_id: int, public_id: UUID):
        return session.execute(text("""
            SELECT id, organization_unit_id, payment_attempt_id, signature_status, processing_state
            FROM public.provider_callback_events
            WHERE tenant_id=:tenant_id AND public_id=:public_id FOR SHARE
        """), {"tenant_id": tenant_id, "public_id": str(public_id)}).mappings().one_or_none()

    @staticmethod
    def public_id_exists(session, public_id: UUID) -> bool:
        return bool(session.execute(text("""
            SELECT 1 FROM (
              SELECT public_id FROM public.canonical_payment_requests WHERE public_id=:id
              UNION ALL SELECT public_id FROM public.canonical_payment_intents WHERE public_id=:id
              UNION ALL SELECT public_id FROM public.canonical_payment_attempts WHERE public_id=:id
              UNION ALL SELECT public_id FROM public.payment_settlements WHERE public_id=:id
              UNION ALL SELECT public_id FROM public.payment_settlement_reversals WHERE public_id=:id
            ) identities LIMIT 1
        """), {"id": str(public_id)}).scalar_one_or_none())

    @staticmethod
    def insert_settlement(session, command: CreatePaymentSettlementCommand, *, intent_id: int,
                          attempt_id: int | None, tender_id: int | None, callback_id: int | None, account_id: int):
        row = session.execute(text(f"""
            INSERT INTO public.payment_settlements (
              public_id, tenant_id, organization_unit_id, payment_intent_id,
              payment_attempt_id, payment_tender_id, provider_callback_event_id, operational_account_id,
              settlement_state, settlement_direction, gross_amount, fee_amount, net_amount,
              currency_code, payment_method_code, payment_rail_code, finality_status,
              availability_state, external_settlement_reference, value_date,
              evidence_payload, occurred_at, business_date, calendar_policy_version,
              correlation_id, actor_user_id, actor_service, source_component,
              source_record_id, idempotency_scope, idempotency_key, request_fingerprint, metadata
            ) VALUES (
              :public_id, :tenant_id, :organization_unit_id, :intent_id,
              :attempt_id, :tender_id, :callback_id, :account_id, 'pending', :settlement_direction,
              :gross_amount, :fee_amount, :net_amount, :currency_code,
              :payment_method_code, :payment_rail_code, 'unverified', 'pending',
              :external_settlement_reference, :value_date, '{{}}'::jsonb,
              :occurred_at, :business_date, :calendar_policy_version,
              :correlation_id, :actor_user_id, :actor_service, :source_component,
              :source_record_id, :idempotency_scope, :idempotency_key,
              :request_fingerprint, CAST(:metadata AS JSONB)
            ) RETURNING {_SETTLEMENT_COLUMNS}
        """), {
            **command.canonical_payload(), "public_id": str(command.public_id),
            "intent_id": intent_id, "attempt_id": attempt_id, "tender_id": tender_id, "callback_id": callback_id,
            "account_id": account_id, "gross_amount": command.gross_amount,
            "fee_amount": command.fee_amount, "net_amount": command.net_amount,
            "correlation_id": str(command.correlation_id),
            "request_fingerprint": command.request_fingerprint,
            "metadata": json.dumps(command.metadata, sort_keys=True),
        }).mappings().one()
        return _settlement(row)

    @staticmethod
    def find_settlement(session, *, tenant_id: int, public_id: UUID, lock=False):
        locking = "FOR UPDATE" if lock else ""
        row = session.execute(text(f"""
            SELECT {_SETTLEMENT_COLUMNS} FROM public.payment_settlements
            WHERE tenant_id=:tenant_id AND public_id=:public_id {locking}
        """), {"tenant_id": tenant_id, "public_id": str(public_id)}).mappings().one_or_none()
        return _settlement(row) if row else None

    @staticmethod
    def insert_transition(session, settlement: PaymentSettlementRecord, command: TransitionPaymentSettlementCommand,
                          *, external_reference: str | None):
        row = session.execute(text(f"""
            INSERT INTO public.payment_settlement_transitions (
              tenant_id, organization_unit_id, payment_settlement_id, sequence_number,
              from_state, to_state, reason_code, finality_status, availability_state,
              failure_code, external_settlement_reference_snapshot, value_date_snapshot,
              evidence_payload, occurred_at, business_date, calendar_policy_version,
              correlation_id, actor_user_id, actor_service, source_component,
              source_record_id, metadata
            ) VALUES (
              :tenant_id, :organization_unit_id, :settlement_id, :sequence_number,
              :from_state, :target_state, :reason_code, :finality_status, :availability_state,
              :failure_code, :external_reference, :value_date, CAST(:evidence AS JSONB),
              :occurred_at, :business_date, :calendar_policy_version,
              :correlation_id, :actor_user_id, :actor_service, :source_component,
              :source_record_id, CAST(:metadata AS JSONB)
            ) RETURNING {_TRANSITION_COLUMNS}
        """), {
            **command.canonical_payload(), "settlement_id": settlement.id,
            "sequence_number": settlement.row_version + 1, "from_state": settlement.settlement_state,
            "external_reference": external_reference, "value_date": settlement.value_date,
            "evidence": json.dumps(command.evidence_payload, sort_keys=True),
            "correlation_id": str(command.correlation_id), "metadata": json.dumps(command.metadata, sort_keys=True),
        }).mappings().one()
        return _transition(row)

    @staticmethod
    def apply_transition(session, settlement: PaymentSettlementRecord, command: TransitionPaymentSettlementCommand,
                         *, external_reference: str | None):
        row = session.execute(text(f"""
            UPDATE public.payment_settlements SET
              settlement_state=:target_state, finality_status=:finality_status,
              availability_state=:availability_state,
              external_settlement_reference=:external_reference,
              terminal_at=:occurred_at, failure_code=:failure_code,
              evidence_payload=CAST(:evidence AS JSONB), row_version=row_version+1, updated_at=now()
            WHERE id=:id AND tenant_id=:tenant_id AND row_version=:expected_row_version
              AND settlement_state=:from_state
            RETURNING {_SETTLEMENT_COLUMNS}
        """), {
            **command.canonical_payload(), "id": settlement.id, "from_state": settlement.settlement_state,
            "external_reference": external_reference,
            "evidence": json.dumps(command.evidence_payload, sort_keys=True),
        }).mappings().one_or_none()
        return _settlement(row) if row else None

    @staticmethod
    def find_transition(session, *, public_id: UUID):
        row = session.execute(text(f"SELECT {_TRANSITION_COLUMNS} FROM public.payment_settlement_transitions WHERE public_id=:id"), {"id": str(public_id)}).mappings().one_or_none()
        return _transition(row) if row else None

    @staticmethod
    def insert_reversal(session, settlement: PaymentSettlementRecord, command: ReversePaymentSettlementCommand):
        row = session.execute(text(f"""
            INSERT INTO public.payment_settlement_reversals (
              public_id, tenant_id, organization_unit_id, payment_settlement_id,
              reversal_amount, currency_code, reason_code, occurred_at, business_date,
              calendar_policy_version, correlation_id, actor_user_id, actor_service,
              source_component, source_record_id, idempotency_scope, idempotency_key,
              request_fingerprint, metadata
            ) VALUES (
              :public_id, :tenant_id, :organization_unit_id, :settlement_id,
              :reversal_amount, :currency_code, :reason_code, :occurred_at, :business_date,
              :calendar_policy_version, :correlation_id, :actor_user_id, :actor_service,
              :source_component, :source_record_id, :idempotency_scope, :idempotency_key,
              :request_fingerprint, CAST(:metadata AS JSONB)
            ) RETURNING {_REVERSAL_COLUMNS}
        """), {
            **command.canonical_payload(), "public_id": str(command.public_id),
            "settlement_id": settlement.id, "reversal_amount": command.reversal_amount,
            "correlation_id": str(command.correlation_id), "request_fingerprint": command.request_fingerprint,
            "metadata": json.dumps(command.metadata, sort_keys=True),
        }).mappings().one()
        return _reversal(row)

    @staticmethod
    def find_reversal(session, *, public_id: UUID):
        row = session.execute(text(f"SELECT {_REVERSAL_COLUMNS} FROM public.payment_settlement_reversals WHERE public_id=:id"), {"id": str(public_id)}).mappings().one_or_none()
        return _reversal(row) if row else None

    @staticmethod
    def transition_history(session, *, tenant_id: int, settlement_id: int):
        return tuple(_transition(row) for row in session.execute(text(f"""
            SELECT {_TRANSITION_COLUMNS} FROM public.payment_settlement_transitions
            WHERE tenant_id=:tenant_id AND payment_settlement_id=:id ORDER BY sequence_number
        """), {"tenant_id": tenant_id, "id": settlement_id}).mappings())
