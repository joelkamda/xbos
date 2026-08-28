"""Persistence helpers for the additive XafPay V2 consumer boundary."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Mapping
from uuid import UUID

from sqlalchemy import text


@dataclass(frozen=True)
class AttemptAuthority:
    id: int
    public_id: UUID
    tenant_id: int
    organization_unit_id: int
    payment_intent_public_id: UUID
    payment_tender_public_id: UUID | None
    attempt_state: str
    attempted_amount: Decimal
    currency_code: str
    payment_method_code: str
    payment_rail_code: str
    orchestrator_code: str
    provider_account_id: int | None
    underlying_provider_code: str | None
    external_attempt_reference: str | None
    occurred_at: datetime
    business_date: date
    calendar_policy_version: int
    correlation_id: UUID
    row_version: int
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class EventReservation:
    id: int
    fingerprint: str
    state: str
    response_snapshot: Mapping[str, Any] | None
    created: bool


class XafPayV2Repository:
    @staticmethod
    def attempt_authority(session, attempt_public_id: UUID, *, lock: bool = False) -> AttemptAuthority | None:
        suffix = "FOR UPDATE OF a" if lock else ""
        row = session.execute(
            text(
                f"""
                SELECT a.id,a.public_id,a.tenant_id,a.organization_unit_id,
                       i.public_id AS payment_intent_public_id,t.public_id AS payment_tender_public_id,
                       a.attempt_state,a.attempted_amount,
                       a.currency_code,a.payment_method_code,a.payment_rail_code,a.orchestrator_code,
                       a.provider_account_id,a.underlying_provider_code,a.external_attempt_reference,
                       a.occurred_at,a.business_date,a.calendar_policy_version,a.correlation_id,a.row_version,a.metadata
                  FROM public.canonical_payment_attempts a
                  JOIN public.canonical_payment_intents i
                    ON i.tenant_id=a.tenant_id AND i.id=a.payment_intent_id
                  LEFT JOIN public.canonical_payment_tenders t
                    ON t.tenant_id=a.tenant_id AND t.id=a.payment_tender_id
                 WHERE a.public_id=:public_id
                 {suffix}
                """
            ),
            {"public_id": str(attempt_public_id)},
        ).mappings().one_or_none()
        if row is None:
            return None
        values = dict(row)
        for key in ("public_id", "payment_intent_public_id", "correlation_id"):
            values[key] = UUID(str(values[key]))
        if values["payment_tender_public_id"] is not None:
            values["payment_tender_public_id"] = UUID(str(values["payment_tender_public_id"]))
        values["attempted_amount"] = Decimal(values["attempted_amount"])
        return AttemptAuthority(**values)

    @classmethod
    def latest_attempt_for_order(cls, session, tenant_id: int, order_id: int) -> AttemptAuthority | None:
        public_id = session.execute(text("""
            SELECT public_id FROM canonical_payment_attempts
             WHERE tenant_id=:tenant_id AND metadata->>'order_id'=:order_id
               AND orchestrator_code='xafpay'
             ORDER BY id DESC LIMIT 1
        """), {"tenant_id": tenant_id, "order_id": str(order_id)}).scalar_one_or_none()
        return cls.attempt_authority(session, UUID(str(public_id)), lock=True) if public_id else None

    @staticmethod
    def finalize_wnd_projection(session, attempt: AttemptAuthority, *, confirmed_at: datetime) -> bool:
        order_id = attempt.metadata.get("order_id")
        sale_id = attempt.metadata.get("sale_id")
        if not isinstance(order_id, int) or not isinstance(sale_id, int):
            return False
        projection = session.execute(text("""
            UPDATE payment_intents
               SET total_paid=LEAST(amount,total_paid+:confirmed_amount),
                   balance_due=GREATEST(0,amount-(total_paid+:confirmed_amount)),
                   status=CASE WHEN amount-(total_paid+:confirmed_amount)<=0
                               THEN 'succeeded' ELSE 'processing' END,
                   gateway_intent_id=:gateway_payment_id,updated_at=:confirmed_at
             WHERE payable_type='sale' AND payable_id=:sale_id AND tenant_id=:tenant_id
             RETURNING balance_due
        """), {"confirmed_at": confirmed_at, "confirmed_amount": attempt.attempted_amount,
                 "gateway_payment_id": attempt.external_attempt_reference,
                 "sale_id": sale_id, "tenant_id": attempt.tenant_id}).mappings().one_or_none()
        if projection is None:
            return False
        remaining = Decimal(projection["balance_due"])
        if remaining <= 0:
            session.execute(text("""
                UPDATE orders SET status='paid',paid_at=:confirmed_at
                 WHERE id=:order_id AND tenant_id=:tenant_id AND status<>'paid'
            """), {"confirmed_at": confirmed_at, "order_id": order_id,
                     "tenant_id": attempt.tenant_id})
            session.execute(text("""
                UPDATE sales SET status='paid',payment_method='split',paid_at=:confirmed_at,
                       unpaid_amount=0
                 WHERE id=:sale_id AND tenant_id=:tenant_id AND status<>'paid'
            """), {"confirmed_at": confirmed_at, "sale_id": sale_id,
                     "tenant_id": attempt.tenant_id})
            return True
        has_ar = session.execute(text("""
            SELECT 1 FROM accounts_receivable
             WHERE tenant_id=:tenant_id AND sale_id=:sale_id AND status IN ('open','partial')
             LIMIT 1
        """), {"tenant_id": attempt.tenant_id, "sale_id": sale_id}).scalar_one_or_none()
        session.execute(text("""
            UPDATE orders SET status=:status
             WHERE id=:order_id AND tenant_id=:tenant_id AND status<>'paid'
        """), {"status": "receivable" if has_ar else "pending_payment",
                 "order_id": order_id, "tenant_id": attempt.tenant_id})
        session.execute(text("""
            UPDATE sales SET status='pending_payment',unpaid_amount=:remaining
             WHERE id=:sale_id AND tenant_id=:tenant_id AND status<>'paid'
        """), {"remaining": remaining, "sale_id": sale_id,
                 "tenant_id": attempt.tenant_id})
        return False

    @staticmethod
    def reserve_event(session, *, tenant_id: int, event_id: str, fingerprint: str) -> EventReservation:
        row = session.execute(
            text(
                """
                INSERT INTO public.idempotency_records(
                    tenant_id,scope,idempotency_key,request_fingerprint,processing_state,locked_until
                ) VALUES(:tenant_id,'xafpay_v2.event',:event_id,:fingerprint,'processing',now()+interval '30 seconds')
                ON CONFLICT (tenant_id,scope,idempotency_key) DO NOTHING
                RETURNING id,request_fingerprint,processing_state,response_snapshot
                """
            ),
            {"tenant_id": tenant_id, "event_id": event_id, "fingerprint": fingerprint},
        ).mappings().one_or_none()
        if row is not None:
            return EventReservation(
                id=int(row["id"]), fingerprint=str(row["request_fingerprint"]),
                state=str(row["processing_state"]), response_snapshot=row["response_snapshot"], created=True,
            )
        existing = session.execute(
            text(
                """
                SELECT id,request_fingerprint,processing_state,response_snapshot
                  FROM public.idempotency_records
                 WHERE tenant_id=:tenant_id AND scope='xafpay_v2.event' AND idempotency_key=:event_id
                 FOR UPDATE
                """
            ),
            {"tenant_id": tenant_id, "event_id": event_id},
        ).mappings().one()
        return EventReservation(
            id=int(existing["id"]), fingerprint=str(existing["request_fingerprint"]),
            state=str(existing["processing_state"]), response_snapshot=existing["response_snapshot"], created=False,
        )

    @staticmethod
    def complete_event(session, reservation: EventReservation, response: Mapping[str, Any]) -> None:
        result = session.execute(
            text(
                """
                UPDATE public.idempotency_records
                   SET processing_state='completed',response_code=200,
                       response_snapshot=CAST(:snapshot AS JSONB),locked_until=NULL,completed_at=now()
                 WHERE id=:id AND request_fingerprint=:fingerprint AND processing_state='processing'
                """
            ),
            {"id": reservation.id, "fingerprint": reservation.fingerprint, "snapshot": json.dumps(dict(response), sort_keys=True)},
        )
        if result.rowcount != 1:
            raise RuntimeError("XV12_EVENT_IDEMPOTENCY_COMPLETION_CONFLICT")

    @staticmethod
    def settlement_count_for_attempt(session, *, tenant_id: int, attempt_public_id: UUID) -> int:
        return int(session.execute(
            text(
                """
                SELECT count(*)
                  FROM public.payment_settlements s
                  JOIN public.canonical_payment_attempts a
                    ON a.tenant_id=s.tenant_id AND a.id=s.payment_attempt_id
                 WHERE s.tenant_id=:tenant_id AND a.public_id=:attempt_public_id
                   AND s.settlement_state IN ('confirmed','partially_reversed')
                """
            ),
            {"tenant_id": tenant_id, "attempt_public_id": str(attempt_public_id)},
        ).scalar_one())

    @staticmethod
    def settlement_for_attempt(session, *, tenant_id: int, attempt_public_id: UUID, lock: bool = False) -> Mapping[str, Any] | None:
        suffix = "FOR UPDATE" if lock else ""
        row = session.execute(
            text(
                f"""
                SELECT s.public_id,s.organization_unit_id,s.gross_amount,s.reversed_amount,s.currency_code,
                       s.settlement_state,s.occurred_at
                  FROM public.payment_settlements s
                  JOIN public.canonical_payment_attempts a
                    ON a.tenant_id=s.tenant_id AND a.id=s.payment_attempt_id
                 WHERE s.tenant_id=:tenant_id AND a.public_id=:attempt_public_id
                   AND s.settlement_state IN ('confirmed','partially_reversed')
                 ORDER BY s.id
                 LIMIT 1
                 {suffix}
                """
            ),
            {"tenant_id": tenant_id, "attempt_public_id": str(attempt_public_id)},
        ).mappings().one_or_none()
        return dict(row) if row is not None else None

    @staticmethod
    def reversal_count_for_attempt(session, *, tenant_id: int, attempt_public_id: UUID) -> int:
        return int(session.execute(
            text(
                """
                SELECT count(*)
                  FROM public.payment_settlement_reversals r
                  JOIN public.payment_settlements s ON s.tenant_id=r.tenant_id AND s.id=r.payment_settlement_id
                  JOIN public.canonical_payment_attempts a ON a.tenant_id=s.tenant_id AND a.id=s.payment_attempt_id
                 WHERE r.tenant_id=:tenant_id AND a.public_id=:attempt_public_id
                """
            ),
            {"tenant_id": tenant_id, "attempt_public_id": str(attempt_public_id)},
        ).scalar_one())

    @staticmethod
    def snapshot_for_attempt(session, attempt_public_id: UUID) -> Mapping[str, Any]:
        row = session.execute(
            text(
                """
                SELECT a.tenant_id,a.organization_unit_id,a.attempt_state,a.external_attempt_reference,
                       a.provider_account_id,a.underlying_provider_code,
                       (SELECT count(*) FROM public.payment_settlements s
                         WHERE s.tenant_id=a.tenant_id AND s.payment_attempt_id=a.id
                           AND s.settlement_state IN ('confirmed','partially_reversed')) AS confirmed_settlements
                  FROM public.canonical_payment_attempts a
                 WHERE a.public_id=:public_id
                """
            ),
            {"public_id": str(attempt_public_id)},
        ).mappings().one()
        return dict(row)
