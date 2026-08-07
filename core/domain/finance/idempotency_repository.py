"""Transactional command-idempotency reservation for neutral finance."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from .event_contract import (
    CanonicalFinancialEventCommand,
    FinancialEventIdempotencyConflict,
    FinancialEventValidationError,
)


@dataclass(frozen=True)
class IdempotencyReservation:
    id: int
    tenant_id: int
    scope: str
    idempotency_key: str
    request_fingerprint: str
    processing_state: str
    response_snapshot: Mapping[str, Any] | None
    created: bool = False


_COLUMNS = """
    id, tenant_id, scope, idempotency_key, request_fingerprint,
    processing_state, response_snapshot
"""

_INSERT = text(
    f"""
    INSERT INTO public.idempotency_records (
        tenant_id, scope, idempotency_key, request_fingerprint,
        processing_state, locked_until
    ) VALUES (
        :tenant_id, :scope, :idempotency_key, :request_fingerprint,
        'processing', now() + interval '30 seconds'
    )
    RETURNING {_COLUMNS}
    """
)

_SELECT_FOR_UPDATE = text(
    f"""
    SELECT {_COLUMNS}
    FROM public.idempotency_records
    WHERE tenant_id = :tenant_id
      AND scope = :scope
      AND idempotency_key = :idempotency_key
    FOR UPDATE
    """
)


class CanonicalIdempotencyRepository:
    """Own the one command reservation inside the caller's transaction."""

    @staticmethod
    def reserve(
        session,
        command: CanonicalFinancialEventCommand,
        request_fingerprint: str,
    ) -> IdempotencyReservation:
        identity = {
            "tenant_id": command.tenant_id,
            "scope": command.idempotency_scope,
            "idempotency_key": command.idempotency_key,
        }
        try:
            with session.begin_nested():
                row = session.execute(
                    _INSERT,
                    {**identity, "request_fingerprint": request_fingerprint},
                ).mappings().one()
            return IdempotencyReservation(**dict(row), created=True)
        except IntegrityError:
            row = session.execute(_SELECT_FOR_UPDATE, identity).mappings().one_or_none()
            if row is None:
                raise FinancialEventValidationError(
                    "idempotency_reservation_lost",
                    "idempotency identity conflicted but no durable record exists",
                )
            record = IdempotencyReservation(**dict(row))
            if record.request_fingerprint != request_fingerprint:
                raise FinancialEventIdempotencyConflict(
                    "idempotency_conflict",
                    "idempotency identity already belongs to different command content",
                )
            if record.processing_state == "completed":
                return record
            if record.processing_state == "processing":
                raise FinancialEventValidationError(
                    "idempotency_in_progress",
                    "the same command is already processing under a bounded lease",
                )
            if record.processing_state == "failed_retryable":
                raise FinancialEventValidationError(
                    "idempotency_retry_authorization_required",
                    "retryable failure requires a recorded retry policy decision",
                )
            if record.processing_state == "failed_terminal":
                raise FinancialEventValidationError(
                    "idempotency_terminal_failure",
                    "the original command ended in a terminal failure",
                )
            raise FinancialEventValidationError(
                "idempotency_state_invalid", "idempotency record has an unknown state"
            )

    @staticmethod
    def complete(
        session,
        reservation: IdempotencyReservation,
        *,
        result_source_record_id: int,
        response_snapshot: Mapping[str, Any],
    ) -> IdempotencyReservation:
        encoded = json.dumps(
            dict(response_snapshot), ensure_ascii=False, sort_keys=True
        )
        row = session.execute(
            text(
                f"""
                UPDATE public.idempotency_records
                SET processing_state = 'completed',
                    result_source_record_id = :result_source_record_id,
                    response_code = 201,
                    response_snapshot = CAST(:response_snapshot AS JSONB),
                    locked_until = NULL,
                    completed_at = now()
                WHERE id = :id
                  AND request_fingerprint = :request_fingerprint
                  AND processing_state = 'processing'
                RETURNING {_COLUMNS}
                """
            ),
            {
                "id": reservation.id,
                "request_fingerprint": reservation.request_fingerprint,
                "result_source_record_id": result_source_record_id,
                "response_snapshot": encoded,
            },
        ).mappings().one_or_none()
        if row is None:
            raise FinancialEventValidationError(
                "idempotency_completion_conflict",
                "idempotency reservation changed before atomic completion",
            )
        return IdempotencyReservation(**dict(row))
