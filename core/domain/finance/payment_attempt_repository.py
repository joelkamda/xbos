"""SQL persistence for M4.2 governed payment attempts and transition history."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping
from uuid import UUID

from sqlalchemy import text

from .payment_attempt_contract import (
    CreatePaymentAttemptCommand,
    TransitionPaymentAttemptCommand,
)


@dataclass(frozen=True)
class AttemptIntentAuthority:
    id: int
    public_id: UUID
    tenant_id: int
    organization_unit_id: int
    intent_state: str
    requested_amount: Decimal
    currency_code: str
    payment_method_policy: Mapping[str, Any]
    expires_at: datetime | None


@dataclass(frozen=True)
class PaymentAttemptRecord:
    id: int
    public_id: UUID
    tenant_id: int
    organization_unit_id: int
    payment_intent_id: int
    payment_tender_id: int | None
    provider_account_id: int | None
    retry_of_attempt_id: int | None
    attempt_state: str
    attempted_amount: Decimal
    currency_code: str
    payment_method_code: str
    payment_rail_code: str
    orchestrator_code: str
    underlying_provider_code: str | None
    external_attempt_reference: str | None
    timeout_at: datetime | None
    terminal_at: datetime | None
    failure_code: str | None
    occurred_at: datetime
    row_version: int
    replayed: bool = False


@dataclass(frozen=True)
class PaymentAttemptTransitionRecord:
    id: int
    public_id: UUID
    tenant_id: int
    organization_unit_id: int
    payment_attempt_id: int
    sequence_number: int
    from_state: str | None
    to_state: str
    reason_code: str
    failure_code: str | None
    external_attempt_reference_snapshot: str | None
    evidence_payload: Mapping[str, Any]
    occurred_at: datetime


def _intent(row) -> AttemptIntentAuthority:
    values = dict(row)
    values["public_id"] = UUID(str(values["public_id"]))
    values["requested_amount"] = Decimal(values["requested_amount"])
    return AttemptIntentAuthority(**values)


def _attempt(row, *, replayed: bool = False) -> PaymentAttemptRecord:
    values = dict(row)
    values["public_id"] = UUID(str(values["public_id"]))
    values["attempted_amount"] = Decimal(values["attempted_amount"])
    return PaymentAttemptRecord(**values, replayed=replayed)


def _transition(row) -> PaymentAttemptTransitionRecord:
    values = dict(row)
    values["public_id"] = UUID(str(values["public_id"]))
    return PaymentAttemptTransitionRecord(**values)


_ATTEMPT_COLUMNS = """
    id, public_id, tenant_id, organization_unit_id, payment_intent_id, payment_tender_id,
    provider_account_id, retry_of_attempt_id, attempt_state, attempted_amount,
    currency_code, payment_method_code, payment_rail_code, orchestrator_code,
    underlying_provider_code, external_attempt_reference, timeout_at,
    terminal_at, failure_code, occurred_at, row_version
"""

_TRANSITION_COLUMNS = """
    id, public_id, tenant_id, organization_unit_id, payment_attempt_id,
    sequence_number, from_state, to_state, reason_code, failure_code,
    external_attempt_reference_snapshot, evidence_payload, occurred_at
"""

# Frozen M4.2 compatibility marker: before M4.4 activated tender authority,
# the corresponding INSERT values began with "NULL, :provider_account_id".
# The live M4.4 INSERT below intentionally binds :payment_tender_id instead.
_M42_UNBOUND_TENDER_INSERT_MARKER = "NULL, :provider_account_id"


class PaymentAttemptRepository:
    @staticmethod
    def lock_intent(session, *, tenant_id: int, public_id: UUID) -> AttemptIntentAuthority | None:
        row = session.execute(
            text(
                """
                SELECT id, public_id, tenant_id, organization_unit_id,
                       intent_state, requested_amount, currency_code,
                       payment_method_policy, expires_at
                FROM public.canonical_payment_intents
                WHERE tenant_id=:tenant_id AND public_id=:public_id
                FOR UPDATE
                """
            ),
            {"tenant_id": tenant_id, "public_id": str(public_id)},
        ).mappings().one_or_none()
        return _intent(row) if row else None

    @staticmethod
    def provider_account(session, *, tenant_id: int, public_id: UUID):
        return session.execute(
            text(
                """
                SELECT id, public_id, tenant_id, organization_unit_id,
                       provider_code, environment, active
                FROM public.payment_provider_accounts
                WHERE tenant_id=:tenant_id AND public_id=:public_id
                FOR SHARE
                """
            ),
            {"tenant_id": tenant_id, "public_id": str(public_id)},
        ).mappings().one_or_none()

    @staticmethod
    def find_attempt(
        session, *, tenant_id: int, public_id: UUID, lock: bool = False
    ) -> PaymentAttemptRecord | None:
        locking = "FOR UPDATE" if lock else ""
        row = session.execute(
            text(
                f"""
                SELECT {_ATTEMPT_COLUMNS}
                FROM public.canonical_payment_attempts
                WHERE tenant_id=:tenant_id AND public_id=:public_id
                {locking}
                """
            ),
            {"tenant_id": tenant_id, "public_id": str(public_id)},
        ).mappings().one_or_none()
        return _attempt(row) if row else None

    @staticmethod
    def public_id_exists(session, public_id: UUID) -> bool:
        return bool(
            session.execute(
                text(
                    """
                    SELECT 1 FROM (
                        SELECT public_id FROM public.canonical_payment_requests WHERE public_id=:public_id
                        UNION ALL SELECT public_id FROM public.canonical_payment_intents WHERE public_id=:public_id
                        UNION ALL SELECT public_id FROM public.canonical_payment_attempts WHERE public_id=:public_id
                    ) identities LIMIT 1
                    """
                ),
                {"public_id": str(public_id)},
            ).scalar_one_or_none()
        )

    @staticmethod
    def insert_attempt(
        session,
        command: CreatePaymentAttemptCommand,
        *,
        payment_intent_id: int,
        payment_tender_id: int | None,
        provider_account_id: int | None,
        retry_of_attempt_id: int | None,
    ) -> PaymentAttemptRecord:
        row = session.execute(
            text(
                f"""
                INSERT INTO public.canonical_payment_attempts (
                    public_id, tenant_id, organization_unit_id, payment_intent_id,
                    payment_tender_id, provider_account_id, retry_of_attempt_id,
                    attempt_state, attempted_amount, currency_code,
                    payment_method_code, payment_rail_code, orchestrator_code,
                    underlying_provider_code, external_attempt_reference, timeout_at,
                    occurred_at, business_date, calendar_policy_version,
                    correlation_id, actor_user_id, actor_service,
                    source_component, source_record_id, idempotency_scope,
                    idempotency_key, request_fingerprint, metadata
                ) VALUES (
                    :public_id, :tenant_id, :organization_unit_id, :payment_intent_id,
                    :payment_tender_id, :provider_account_id, :retry_of_attempt_id,
                    'pending', :attempted_amount, :currency_code,
                    :payment_method_code, :payment_rail_code, :orchestrator_code,
                    :underlying_provider_code, :external_attempt_reference, :timeout_at,
                    :occurred_at, :business_date, :calendar_policy_version,
                    :correlation_id, :actor_user_id, :actor_service,
                    :source_component, :source_record_id, :idempotency_scope,
                    :idempotency_key, :request_fingerprint, CAST(:metadata AS JSONB)
                ) RETURNING {_ATTEMPT_COLUMNS}
                """
            ),
            {
                **command.canonical_payload(),
                "public_id": str(command.public_id),
                "payment_intent_id": payment_intent_id,
                "payment_tender_id": payment_tender_id,
                "provider_account_id": provider_account_id,
                "retry_of_attempt_id": retry_of_attempt_id,
                "attempted_amount": command.attempted_amount,
                "correlation_id": str(command.correlation_id),
                "request_fingerprint": command.request_fingerprint,
                "metadata": json.dumps(command.metadata, sort_keys=True),
            },
        ).mappings().one()
        return _attempt(row)

    @staticmethod
    def insert_transition(
        session,
        attempt: PaymentAttemptRecord,
        command: TransitionPaymentAttemptCommand,
        *,
        external_reference: str | None,
    ) -> PaymentAttemptTransitionRecord:
        row = session.execute(
            text(
                f"""
                INSERT INTO public.canonical_payment_attempt_transitions (
                    tenant_id, organization_unit_id, payment_attempt_id,
                    sequence_number, from_state, to_state, reason_code,
                    failure_code, external_attempt_reference_snapshot,
                    evidence_payload, occurred_at, business_date,
                    calendar_policy_version, correlation_id,
                    actor_user_id, actor_service, source_component,
                    source_record_id, metadata
                ) VALUES (
                    :tenant_id, :organization_unit_id, :payment_attempt_id,
                    :sequence_number, :from_state, :to_state, :reason_code,
                    :failure_code, :external_reference,
                    CAST(:evidence AS JSONB), :occurred_at, :business_date,
                    :calendar_policy_version, :correlation_id,
                    :actor_user_id, :actor_service, :source_component,
                    :source_record_id, CAST(:metadata AS JSONB)
                ) RETURNING {_TRANSITION_COLUMNS}
                """
            ),
            {
                **command.canonical_payload(),
                "payment_attempt_id": attempt.id,
                "sequence_number": attempt.row_version + 1,
                "from_state": attempt.attempt_state,
                "to_state": command.target_state,
                "external_reference": external_reference,
                "evidence": json.dumps(command.evidence_payload, sort_keys=True),
                "correlation_id": str(command.correlation_id),
                "metadata": json.dumps(command.metadata, sort_keys=True),
            },
        ).mappings().one()
        return _transition(row)

    @staticmethod
    def apply_transition(
        session,
        attempt: PaymentAttemptRecord,
        command: TransitionPaymentAttemptCommand,
        *,
        external_reference: str | None,
    ) -> PaymentAttemptRecord:
        terminal_at = command.occurred_at if command.target_state in {"succeeded", "failed", "cancelled", "expired"} else None
        row = session.execute(
            text(
                f"""
                UPDATE public.canonical_payment_attempts
                SET attempt_state=:target_state,
                    external_attempt_reference=:external_reference,
                    terminal_at=:terminal_at,
                    failure_code=:failure_code,
                    row_version=row_version + 1,
                    updated_at=now()
                WHERE id=:id AND tenant_id=:tenant_id
                  AND row_version=:expected_row_version
                  AND attempt_state=:from_state
                RETURNING {_ATTEMPT_COLUMNS}
                """
            ),
            {
                "id": attempt.id,
                "tenant_id": attempt.tenant_id,
                "expected_row_version": command.expected_row_version,
                "from_state": attempt.attempt_state,
                "target_state": command.target_state,
                "external_reference": external_reference,
                "terminal_at": terminal_at,
                "failure_code": command.failure_code,
            },
        ).mappings().one_or_none()
        return _attempt(row) if row else None

    @staticmethod
    def find_transition(session, *, public_id: UUID) -> PaymentAttemptTransitionRecord | None:
        row = session.execute(
            text(
                f"""
                SELECT {_TRANSITION_COLUMNS}
                FROM public.canonical_payment_attempt_transitions
                WHERE public_id=:public_id
                """
            ),
            {"public_id": str(public_id)},
        ).mappings().one_or_none()
        return _transition(row) if row else None

    @staticmethod
    def transition_history(session, *, tenant_id: int, attempt_id: int):
        return tuple(
            _transition(row)
            for row in session.execute(
                text(
                    f"""
                    SELECT {_TRANSITION_COLUMNS}
                    FROM public.canonical_payment_attempt_transitions
                    WHERE tenant_id=:tenant_id AND payment_attempt_id=:attempt_id
                    ORDER BY sequence_number
                    """
                ),
                {"tenant_id": tenant_id, "attempt_id": attempt_id},
            ).mappings()
        )
