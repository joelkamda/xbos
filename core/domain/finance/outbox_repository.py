"""Immutable transactional outbox persistence for canonical finance events."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from .event_contract import (
    FinancialEventValidationError,
    canonical_decimal,
    canonical_json_bytes,
    canonical_timestamp,
)
from .event_repository import FinancialEventRecord


OUTBOX_TOPIC = "finance.financial-events.v1"


@dataclass(frozen=True)
class OutboxMessageRecord:
    id: int
    public_id: UUID
    tenant_id: int
    organization_unit_id: int
    source_event_public_id: UUID
    topic: str
    message_key: str
    event_name: str
    event_version: int
    payload: Mapping[str, Any]
    payload_hash: str
    delivery_state: str
    occurred_at: datetime
    recorded_at: datetime
    correlation_id: UUID
    causation_id: UUID | None

    @classmethod
    def from_row(cls, row) -> "OutboxMessageRecord":
        values = dict(row)
        for name in (
            "public_id",
            "source_event_public_id",
            "correlation_id",
            "causation_id",
        ):
            if values.get(name) is not None:
                values[name] = UUID(str(values[name]))
        return cls(**values)


_COLUMNS = """
    id, public_id, tenant_id, organization_unit_id,
    source_event_public_id, topic, message_key, event_name, event_version,
    payload, payload_hash, delivery_state, occurred_at, recorded_at,
    correlation_id, causation_id
"""

_FIND = text(
    f"""
    SELECT {_COLUMNS}
    FROM public.outbox_messages
    WHERE tenant_id = :tenant_id
      AND source_event_public_id = :source_event_public_id
    """
)


def _event_payload(event: FinancialEventRecord, message_id: UUID) -> dict[str, Any]:
    return {
        "message_id": str(message_id),
        "tenant_id": event.tenant_id,
        "organization_unit_id": event.organization_unit_id,
        "topic": OUTBOX_TOPIC,
        "event_type": event.event_type_code,
        "event_version": event.event_version,
        "message_key": str(event.public_id),
        "correlation_id": str(event.correlation_id),
        "causation_id": str(event.causation_id) if event.causation_id else None,
        "occurred_at": canonical_timestamp(event.occurred_at),
        "recorded_at": canonical_timestamp(event.recorded_at),
        "payload": {
            "financial_event_id": str(event.public_id),
            "amount": canonical_decimal(event.amount),
            "currency_code": event.currency_code,
            "economic_role": event.economic_role,
            "source_record_id": event.source_record_id,
            "business_date": event.business_date.isoformat(),
            "calendar_policy_version": event.calendar_policy_version,
            "source_operational_account_id": event.source_operational_account_id,
            "target_operational_account_id": event.target_operational_account_id,
            "original_event_id": event.original_event_id,
            "classification_snapshot": event.classification_snapshot,
            "posting_context": event.posting_context,
            "evidence_hash": event.evidence_hash,
        },
    }


class CanonicalOutboxRepository:
    @staticmethod
    def find_for_event(session, event: FinancialEventRecord):
        row = session.execute(
            _FIND,
            {
                "tenant_id": event.tenant_id,
                "source_event_public_id": event.public_id,
            },
        ).mappings().one_or_none()
        return OutboxMessageRecord.from_row(row) if row else None

    @staticmethod
    def ensure_for_event(session, event: FinancialEventRecord) -> OutboxMessageRecord:
        existing = CanonicalOutboxRepository.find_for_event(session, event)
        if existing is not None:
            return existing

        message_id = uuid4()
        payload = _event_payload(event, message_id)
        payload_hash = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        parameters = {
            "public_id": message_id,
            "tenant_id": event.tenant_id,
            "organization_unit_id": event.organization_unit_id,
            "source_event_public_id": event.public_id,
            "aggregate_type": "financial_event",
            "aggregate_public_id": event.public_id,
            "topic": OUTBOX_TOPIC,
            "message_key": str(event.public_id),
            "event_name": event.event_type_code,
            "event_version": event.event_version,
            "payload": json.dumps(payload, ensure_ascii=False, sort_keys=True),
            "payload_hash": payload_hash,
            "occurred_at": event.occurred_at,
            "recorded_at": event.recorded_at,
            "correlation_id": event.correlation_id,
            "causation_id": event.causation_id,
        }
        try:
            with session.begin_nested():
                row = session.execute(
                    text(
                        f"""
                        INSERT INTO public.outbox_messages (
                            public_id, tenant_id, organization_unit_id,
                            source_event_public_id, aggregate_type,
                            aggregate_public_id, topic, message_key,
                            event_name, event_version, payload, payload_hash,
                            delivery_state, occurred_at, recorded_at,
                            correlation_id, causation_id
                        ) VALUES (
                            :public_id, :tenant_id, :organization_unit_id,
                            :source_event_public_id, :aggregate_type,
                            :aggregate_public_id, :topic, :message_key,
                            :event_name, :event_version, CAST(:payload AS JSONB),
                            :payload_hash, 'pending', :occurred_at, :recorded_at,
                            :correlation_id, :causation_id
                        )
                        RETURNING {_COLUMNS}
                        """
                    ),
                    parameters,
                ).mappings().one()
            return OutboxMessageRecord.from_row(row)
        except IntegrityError:
            winner = CanonicalOutboxRepository.find_for_event(session, event)
            if winner is None:
                raise FinancialEventValidationError(
                    "outbox_identity_conflict",
                    "outbox identity conflicted without a matching event message",
                )
            if winner.topic != OUTBOX_TOPIC or winner.message_key != str(event.public_id):
                raise FinancialEventValidationError(
                    "outbox_identity_conflict",
                    "financial event is already bound to a different message identity",
                )
            return winner
