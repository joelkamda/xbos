"""SQL persistence for typed obligations and their command idempotency."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from .obligation_contract import (
    CreateObligationCommand,
    ObligationIdempotencyConflict,
    ObligationValidationError,
)


@dataclass(frozen=True)
class ObligationRecord:
    id: int
    public_id: UUID
    tenant_id: int
    organization_unit_id: int
    obligation_state: str
    original_amount: Decimal
    currency_code: str
    row_version: int
    line_count: int
    replayed: bool = False


@dataclass(frozen=True)
class ObligationIdempotencyReservation:
    id: int
    tenant_id: int
    scope: str
    idempotency_key: str
    request_fingerprint: str
    processing_state: str
    response_snapshot: Mapping[str, Any] | None
    created: bool = False


_IDEMPOTENCY_COLUMNS = """
    id, tenant_id, scope, idempotency_key, request_fingerprint,
    processing_state, response_snapshot
"""


def _reservation(row, *, created: bool = False) -> ObligationIdempotencyReservation:
    return ObligationIdempotencyReservation(**dict(row), created=created)


class ObligationRepository:
    @staticmethod
    def reserve(session, command, fingerprint: str) -> ObligationIdempotencyReservation:
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
                    WHERE tenant_id = :tenant_id AND scope = :scope
                      AND idempotency_key = :idempotency_key
                    FOR UPDATE
                    """
                ),
                identity,
            ).mappings().one_or_none()
            if row is None:
                raise ObligationValidationError("idempotency_lost", "conflict has no durable reservation")
            reservation = _reservation(row)
            if reservation.request_fingerprint != fingerprint:
                raise ObligationIdempotencyConflict(
                    "obligation_idempotency_conflict",
                    "idempotency identity belongs to different obligation command content",
                )
            if reservation.processing_state == "completed":
                return reservation
            if reservation.processing_state == "processing":
                raise ObligationValidationError("obligation_idempotency_in_progress", "command is processing")
            raise ObligationValidationError("obligation_idempotency_terminal", "command cannot be replayed")

    @staticmethod
    def complete(
        session,
        reservation: ObligationIdempotencyReservation,
        *,
        response_snapshot: Mapping[str, Any],
        response_code: int,
    ) -> ObligationIdempotencyReservation:
        row = session.execute(
            text(
                f"""
                UPDATE public.idempotency_records
                SET processing_state = 'completed', response_code = :response_code,
                    response_snapshot = CAST(:snapshot AS JSONB),
                    locked_until = NULL, completed_at = now()
                WHERE id = :id AND request_fingerprint = :fingerprint
                  AND processing_state = 'processing'
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
            raise ObligationValidationError("idempotency_completion_conflict", "reservation changed")
        return _reservation(row)

    @staticmethod
    def insert(session, command: CreateObligationCommand) -> ObligationRecord:
        obligation = session.execute(
            text(
                """
                INSERT INTO public.financial_obligations (
                    public_id, tenant_id, organization_unit_id,
                    debtor_party_id, creditor_party_id, commercial_transaction_public_id,
                    obligation_type, obligation_state, original_amount, currency_code,
                    due_at, occurred_at, business_date, calendar_policy_version,
                    correlation_id, actor_user_id, actor_service,
                    source_component, source_record_id,
                    idempotency_scope, idempotency_key, request_fingerprint, metadata
                ) VALUES (
                    :public_id, :tenant_id, :organization_unit_id,
                    :debtor_party_id, :creditor_party_id, :commercial_transaction_public_id,
                    :obligation_type, 'open', :original_amount, :currency_code,
                    :due_at, :occurred_at, :business_date, :calendar_policy_version,
                    :correlation_id, :actor_user_id, :actor_service,
                    :source_component, :source_record_id,
                    :idempotency_scope, :idempotency_key, :request_fingerprint,
                    CAST(:metadata AS JSONB)
                )
                RETURNING id, public_id, tenant_id, organization_unit_id,
                          obligation_state, original_amount, currency_code, row_version
                """
            ),
            {
                **command.canonical_payload(),
                "public_id": str(command.public_id),
                "debtor_party_id": str(command.debtor_party_id),
                "creditor_party_id": str(command.creditor_party_id),
                "commercial_transaction_public_id": str(command.commercial_transaction_public_id) if command.commercial_transaction_public_id else None,
                "correlation_id": str(command.correlation_id),
                "original_amount": command.original_amount,
                "request_fingerprint": command.request_fingerprint,
                "metadata": json.dumps(dict(command.metadata), sort_keys=True),
            },
        ).mappings().one()
        for line in command.lines:
            session.execute(
                text(
                    """
                    INSERT INTO public.financial_obligation_lines (
                        tenant_id, organization_unit_id, obligation_id,
                        line_number, line_type, description_snapshot,
                        quantity, unit_amount, line_amount, currency_code,
                        occurred_at, business_date, calendar_policy_version,
                        correlation_id, actor_user_id, actor_service,
                        source_component, source_record_id, metadata
                    ) VALUES (
                        :tenant_id, :organization_unit_id, :obligation_id,
                        :line_number, :line_type, :description,
                        :quantity, :unit_amount, :line_amount, :currency_code,
                        :occurred_at, :business_date, :calendar_policy_version,
                        :correlation_id, :actor_user_id, :actor_service,
                        :source_component, :source_record_id, CAST(:metadata AS JSONB)
                    )
                    """
                ),
                {
                    "tenant_id": command.tenant_id,
                    "organization_unit_id": command.organization_unit_id,
                    "obligation_id": obligation["id"],
                    "line_number": line.line_number,
                    "line_type": line.line_type,
                    "description": line.description,
                    "quantity": line.quantity,
                    "unit_amount": line.unit_amount,
                    "line_amount": line.line_amount,
                    "currency_code": command.currency_code,
                    "occurred_at": command.occurred_at,
                    "business_date": command.business_date,
                    "calendar_policy_version": command.calendar_policy_version,
                    "correlation_id": str(command.correlation_id),
                    "actor_user_id": command.actor_user_id,
                    "actor_service": command.actor_service,
                    "source_component": command.source_component,
                    "source_record_id": line.source_record_id,
                    "metadata": json.dumps(dict(line.metadata), sort_keys=True),
                },
            )
        values = dict(obligation)
        values["public_id"] = UUID(str(values["public_id"]))
        values["original_amount"] = Decimal(values["original_amount"])
        values["line_count"] = len(command.lines)
        return ObligationRecord(**values)

    @staticmethod
    def find_by_public_id(session, *, tenant_id: int, public_id: UUID) -> ObligationRecord | None:
        row = session.execute(
            text(
                """
                SELECT o.id, o.public_id, o.tenant_id, o.organization_unit_id,
                       o.obligation_state, o.original_amount, o.currency_code,
                       o.row_version, count(l.id) AS line_count
                FROM public.financial_obligations o
                LEFT JOIN public.financial_obligation_lines l
                  ON l.tenant_id = o.tenant_id AND l.obligation_id = o.id
                WHERE o.tenant_id = :tenant_id AND o.public_id = :public_id
                GROUP BY o.id
                """
            ),
            {"tenant_id": tenant_id, "public_id": str(public_id)},
        ).mappings().one_or_none()
        if row is None:
            return None
        values = dict(row)
        values["public_id"] = UUID(str(values["public_id"]))
        values["original_amount"] = Decimal(values["original_amount"])
        return ObligationRecord(**values)

    @staticmethod
    def lock(session, *, tenant_id: int, public_id: UUID):
        row = session.execute(
            text(
                """
                SELECT id, obligation_state, row_version
                FROM public.financial_obligations
                WHERE tenant_id = :tenant_id AND public_id = :public_id
                FOR UPDATE
                """
            ),
            {"tenant_id": tenant_id, "public_id": str(public_id)},
        ).mappings().one_or_none()
        if row is None:
            raise ObligationValidationError("obligation_not_found", "obligation does not exist for tenant")
        return row

    @staticmethod
    def update_state(session, *, obligation_id: int, expected_version: int, target_state: str) -> None:
        changed = session.execute(
            text(
                """
                UPDATE public.financial_obligations
                SET obligation_state = :target_state, row_version = row_version + 1
                WHERE id = :id AND row_version = :expected_version
                """
            ),
            {"id": obligation_id, "expected_version": expected_version, "target_state": target_state},
        ).rowcount
        if changed != 1:
            raise ObligationValidationError("obligation_version_conflict", "obligation row version changed")
