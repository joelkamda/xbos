"""Transactional SQL persistence for M4.1 payment request and intent commands."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from .payment_intent_contract import (
    CreatePaymentIntentCommand,
    CreatePaymentRequestCommand,
    PaymentCommandIdempotencyConflict,
    PaymentCommandValidationError,
)


@dataclass(frozen=True)
class PaymentIdempotencyReservation:
    id: int
    tenant_id: int
    scope: str
    idempotency_key: str
    request_fingerprint: str
    processing_state: str
    response_snapshot: Mapping[str, Any] | None
    created: bool = False


@dataclass(frozen=True)
class PaymentRequestRecord:
    id: int
    public_id: UUID
    tenant_id: int
    organization_unit_id: int
    request_state: str
    purpose_code: str
    requested_amount: Decimal
    currency_code: str
    expires_at: datetime | None
    row_version: int
    committed_intent_amount: Decimal
    replayed: bool = False


@dataclass(frozen=True)
class PaymentIntentRecord:
    id: int
    public_id: UUID
    tenant_id: int
    organization_unit_id: int
    payment_request_id: int | None
    financial_obligation_public_id: UUID | None
    intent_state: str
    requested_amount: Decimal
    currency_code: str
    payment_method_policy: Mapping[str, Any]
    row_version: int
    replayed: bool = False


_IDEMPOTENCY_COLUMNS = """
    id, tenant_id, scope, idempotency_key, request_fingerprint,
    processing_state, response_snapshot
"""


def _reservation(row, *, created: bool = False) -> PaymentIdempotencyReservation:
    return PaymentIdempotencyReservation(**dict(row), created=created)


def _request_record(row, *, replayed: bool = False) -> PaymentRequestRecord:
    values = dict(row)
    values["public_id"] = UUID(str(values["public_id"]))
    values["requested_amount"] = Decimal(values["requested_amount"])
    values["committed_intent_amount"] = Decimal(values["committed_intent_amount"])
    return PaymentRequestRecord(**values, replayed=replayed)


def _intent_record(row, *, replayed: bool = False) -> PaymentIntentRecord:
    values = dict(row)
    values["public_id"] = UUID(str(values["public_id"]))
    if values["financial_obligation_public_id"] is not None:
        values["financial_obligation_public_id"] = UUID(str(values["financial_obligation_public_id"]))
    values["requested_amount"] = Decimal(values["requested_amount"])
    return PaymentIntentRecord(**values, replayed=replayed)


class PaymentIntentRepository:
    @staticmethod
    def reserve(session, command, fingerprint: str) -> PaymentIdempotencyReservation:
        identity = {
            "tenant_id": command.tenant_id,
            "scope": command.idempotency_scope,
            "idempotency_key": command.idempotency_key,
        }
        try:
            with session.begin_nested():
                row = session.execute(
                    text(
                        f"""
                        INSERT INTO public.idempotency_records (
                            tenant_id, scope, idempotency_key, request_fingerprint,
                            processing_state, locked_until
                        ) VALUES (
                            :tenant_id, :scope, :idempotency_key, :fingerprint,
                            'processing', now() + interval '30 seconds'
                        ) RETURNING {_IDEMPOTENCY_COLUMNS}
                        """
                    ),
                    {**identity, "fingerprint": fingerprint},
                ).mappings().one()
            return _reservation(row, created=True)
        except IntegrityError:
            row = session.execute(
                text(
                    f"""
                    SELECT {_IDEMPOTENCY_COLUMNS}
                    FROM public.idempotency_records
                    WHERE tenant_id=:tenant_id AND scope=:scope
                      AND idempotency_key=:idempotency_key
                    FOR UPDATE
                    """
                ),
                identity,
            ).mappings().one_or_none()
            if row is None:
                raise PaymentCommandValidationError("idempotency_lost", "conflict has no durable reservation")
            reservation = _reservation(row)
            if reservation.request_fingerprint != fingerprint:
                raise PaymentCommandIdempotencyConflict(
                    "payment_command_idempotency_conflict",
                    "idempotency identity belongs to different payment command content",
                )
            if reservation.processing_state == "completed":
                return reservation
            if reservation.processing_state == "processing":
                raise PaymentCommandValidationError("payment_command_in_progress", "command is processing")
            raise PaymentCommandValidationError("payment_command_terminal", "command cannot be replayed")

    @staticmethod
    def complete(
        session,
        reservation: PaymentIdempotencyReservation,
        *,
        response_snapshot: Mapping[str, Any],
        response_code: int,
    ) -> PaymentIdempotencyReservation:
        row = session.execute(
            text(
                f"""
                UPDATE public.idempotency_records
                SET processing_state='completed', response_code=:response_code,
                    response_snapshot=CAST(:snapshot AS JSONB),
                    locked_until=NULL, completed_at=now()
                WHERE id=:id AND request_fingerprint=:fingerprint
                  AND processing_state='processing'
                RETURNING {_IDEMPOTENCY_COLUMNS}
                """
            ),
            {
                "id": reservation.id,
                "fingerprint": reservation.request_fingerprint,
                "response_code": response_code,
                "snapshot": json.dumps(dict(response_snapshot), sort_keys=True),
            },
        ).mappings().one_or_none()
        if row is None:
            raise PaymentCommandValidationError("idempotency_completion_conflict", "reservation changed")
        return _reservation(row)

    @staticmethod
    def public_id_exists(session, public_id: UUID) -> bool:
        return bool(
            session.execute(
                text(
                    """
                    SELECT 1 FROM (
                        SELECT public_id FROM public.canonical_payment_requests WHERE public_id=:public_id
                        UNION ALL
                        SELECT public_id FROM public.canonical_payment_intents WHERE public_id=:public_id
                    ) identities LIMIT 1
                    """
                ),
                {"public_id": str(public_id)},
            ).scalar_one_or_none()
        )

    @staticmethod
    def insert_request(session, command: CreatePaymentRequestCommand) -> PaymentRequestRecord:
        row = session.execute(
            text(
                """
                INSERT INTO public.canonical_payment_requests (
                    public_id, tenant_id, organization_unit_id, payer_party_id,
                    request_state, purpose_code, requested_amount, currency_code,
                    expires_at, occurred_at, business_date, calendar_policy_version,
                    correlation_id, actor_user_id, actor_service,
                    source_component, source_record_id,
                    idempotency_scope, idempotency_key, request_fingerprint, metadata
                ) VALUES (
                    :public_id, :tenant_id, :organization_unit_id, :payer_party_id,
                    'open', :purpose_code, :requested_amount, :currency_code,
                    :expires_at, :occurred_at, :business_date, :calendar_policy_version,
                    :correlation_id, :actor_user_id, :actor_service,
                    :source_component, :source_record_id,
                    :idempotency_scope, :idempotency_key, :request_fingerprint,
                    CAST(:metadata AS JSONB)
                )
                RETURNING id, public_id, tenant_id, organization_unit_id,
                          request_state, purpose_code, requested_amount,
                          currency_code, expires_at, row_version,
                          0::numeric AS committed_intent_amount
                """
            ),
            {
                **command.canonical_payload(),
                "public_id": str(command.public_id),
                "payer_party_id": str(command.payer_party_id) if command.payer_party_id else None,
                "requested_amount": command.requested_amount,
                "correlation_id": str(command.correlation_id),
                "request_fingerprint": command.request_fingerprint,
                "metadata": json.dumps(command.metadata, sort_keys=True),
            },
        ).mappings().one()
        return _request_record(row)

    @staticmethod
    def find_request(session, *, tenant_id: int, public_id: UUID, lock: bool = False) -> PaymentRequestRecord | None:
        locking = "FOR UPDATE OF r" if lock else ""
        row = session.execute(
            text(
                f"""
                SELECT r.id, r.public_id, r.tenant_id, r.organization_unit_id,
                       r.request_state, r.purpose_code, r.requested_amount,
                       r.currency_code, r.expires_at, r.row_version,
                       COALESCE((
                           SELECT sum(i.requested_amount)
                           FROM public.canonical_payment_intents i
                           WHERE i.tenant_id=r.tenant_id AND i.payment_request_id=r.id
                             AND i.intent_state NOT IN ('failed','cancelled','expired')
                       ), 0) AS committed_intent_amount
                FROM public.canonical_payment_requests r
                WHERE r.tenant_id=:tenant_id AND r.public_id=:public_id
                {locking}
                """
            ),
            {"tenant_id": tenant_id, "public_id": str(public_id)},
        ).mappings().one_or_none()
        return _request_record(row) if row else None

    @staticmethod
    def lock_obligation(session, *, tenant_id: int, public_id: UUID):
        return session.execute(
            text(
                """
                SELECT id, public_id, tenant_id, organization_unit_id,
                       obligation_state, original_amount, currency_code
                FROM public.financial_obligations
                WHERE tenant_id=:tenant_id AND public_id=:public_id
                FOR UPDATE
                """
            ),
            {"tenant_id": tenant_id, "public_id": str(public_id)},
        ).mappings().one_or_none()

    @staticmethod
    def insert_intent(
        session,
        command: CreatePaymentIntentCommand,
        *,
        payment_request_id: int | None,
    ) -> PaymentIntentRecord:
        row = session.execute(
            text(
                """
                INSERT INTO public.canonical_payment_intents (
                    public_id, tenant_id, organization_unit_id, payment_request_id,
                    financial_obligation_public_id, intent_state, requested_amount,
                    currency_code, payment_method_policy, expires_at,
                    occurred_at, business_date, calendar_policy_version,
                    correlation_id, actor_user_id, actor_service,
                    source_component, source_record_id,
                    idempotency_scope, idempotency_key, request_fingerprint, metadata
                ) VALUES (
                    :public_id, :tenant_id, :organization_unit_id, :payment_request_id,
                    :financial_obligation_public_id, 'pending', :requested_amount,
                    :currency_code, CAST(:payment_method_policy AS JSONB), :expires_at,
                    :occurred_at, :business_date, :calendar_policy_version,
                    :correlation_id, :actor_user_id, :actor_service,
                    :source_component, :source_record_id,
                    :idempotency_scope, :idempotency_key, :request_fingerprint,
                    CAST(:metadata AS JSONB)
                )
                RETURNING id, public_id, tenant_id, organization_unit_id,
                          payment_request_id, financial_obligation_public_id,
                          intent_state, requested_amount, currency_code,
                          payment_method_policy, row_version
                """
            ),
            {
                **command.canonical_payload(),
                "public_id": str(command.public_id),
                "payment_request_id": payment_request_id,
                "financial_obligation_public_id": (
                    str(command.financial_obligation_public_id)
                    if command.financial_obligation_public_id else None
                ),
                "requested_amount": command.requested_amount,
                "payment_method_policy": json.dumps(command.payment_method_policy, sort_keys=True),
                "correlation_id": str(command.correlation_id),
                "request_fingerprint": command.request_fingerprint,
                "metadata": json.dumps(command.metadata, sort_keys=True),
            },
        ).mappings().one()
        return _intent_record(row)

    @staticmethod
    def find_intent(session, *, tenant_id: int, public_id: UUID) -> PaymentIntentRecord | None:
        row = session.execute(
            text(
                """
                SELECT id, public_id, tenant_id, organization_unit_id,
                       payment_request_id, financial_obligation_public_id,
                       intent_state, requested_amount, currency_code,
                       payment_method_policy, row_version
                FROM public.canonical_payment_intents
                WHERE tenant_id=:tenant_id AND public_id=:public_id
                """
            ),
            {"tenant_id": tenant_id, "public_id": str(public_id)},
        ).mappings().one_or_none()
        return _intent_record(row) if row else None
