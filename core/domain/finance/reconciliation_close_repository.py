"""Persistence for M6.3 reconciliation-window governance transitions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text


@dataclass(frozen=True)
class ReconciliationGovernanceEvent:
    id: int
    public_id: UUID
    tenant_id: int
    organization_unit_id: int
    reconciliation_window_id: int
    transition_type: str
    prior_event_id: int | None
    governed_revision_id: int
    governed_revision_number: int
    accounting_period_id: int
    accounting_period_code: str
    accounting_period_state: str
    close_disposition: str | None
    transition_reason: str
    evidence_hash: str
    approved_by_user_id: int | None
    approved_at: object | None
    occurred_at: object
    request_fingerprint: str
    replayed: bool = False


def _event(row, *, replayed=False):
    return ReconciliationGovernanceEvent(
        int(row["id"]), UUID(str(row["public_id"])), int(row["tenant_id"]),
        int(row["organization_unit_id"]), int(row["reconciliation_window_id"]),
        row["transition_type"], int(row["prior_event_id"]) if row["prior_event_id"] is not None else None,
        int(row["governed_revision_id"]), int(row["governed_revision_number"]),
        int(row["accounting_period_id"]), row["accounting_period_code"], row["accounting_period_state"],
        row["close_disposition"], row["transition_reason"], row["evidence_hash"],
        int(row["approved_by_user_id"]) if row["approved_by_user_id"] is not None else None,
        row["approved_at"], row["occurred_at"], row["request_fingerprint"].strip(), replayed,
    )


class ReconciliationCloseRepository:
    EVENT_COLUMNS = """id,public_id,tenant_id,organization_unit_id,reconciliation_window_id,transition_type,
prior_event_id,governed_revision_id,governed_revision_number,accounting_period_id,accounting_period_code,
accounting_period_state,close_disposition,transition_reason,evidence_hash,approved_by_user_id,approved_at,
occurred_at,request_fingerprint"""

    @classmethod
    def by_idempotency(cls, session, command):
        row = session.execute(text(f"""SELECT {cls.EVENT_COLUMNS} FROM reconciliation_window_governance_events
            WHERE tenant_id=:tenant AND idempotency_scope=:scope AND idempotency_key=:key FOR UPDATE"""), {
            "tenant": command.tenant_id, "scope": command.idempotency_scope, "key": command.idempotency_key,
        }).mappings().one_or_none()
        return _event(row, replayed=True) if row else None

    @staticmethod
    def authority(session, command):
        return session.execute(text("""SELECT w.id window_id,w.organization_unit_id,w.business_date,w.calendar_policy_version,
            w.predecessor_window_id,s.operational_account_id,r.id revision_id,r.revision_number,r.variance,
            r.readiness_condition,p.id accounting_period_id,p.period_code,p.period_state
            FROM reconciliation_windows w JOIN reconciliation_series s ON s.tenant_id=w.tenant_id AND s.id=w.reconciliation_series_id
            JOIN current_reconciliation_window_revisions r ON r.tenant_id=w.tenant_id AND r.reconciliation_window_id=w.id
            LEFT JOIN accounting_periods p ON p.tenant_id=w.tenant_id AND p.legal_entity_unit_id=w.organization_unit_id
              AND w.business_date BETWEEN p.period_start AND p.period_end
            WHERE w.tenant_id=:tenant AND w.public_id=:public FOR UPDATE OF w"""), {
            "tenant": command.tenant_id, "public": str(command.reconciliation_window_public_id),
        }).mappings().one_or_none()

    @classmethod
    def latest(cls, session, *, tenant_id, window_id, lock=False):
        locking = "FOR UPDATE" if lock else ""
        row = session.execute(text(f"""SELECT {cls.EVENT_COLUMNS} FROM reconciliation_window_governance_events
            WHERE tenant_id=:tenant AND reconciliation_window_id=:window ORDER BY id DESC LIMIT 1 {locking}"""), {
            "tenant": tenant_id, "window": window_id,
        }).mappings().one_or_none()
        return _event(row) if row else None

    @classmethod
    def by_public_id(cls, session, *, tenant_id, public_id):
        row = session.execute(text(f"SELECT {cls.EVENT_COLUMNS} FROM reconciliation_window_governance_events WHERE tenant_id=:tenant AND public_id=:public"), {
            "tenant": tenant_id, "public": str(public_id),
        }).mappings().one_or_none()
        return _event(row) if row else None

    @classmethod
    def predecessor_latest(cls, session, *, tenant_id, predecessor_window_id):
        if predecessor_window_id is None:
            return None
        return cls.latest(session, tenant_id=tenant_id, window_id=predecessor_window_id, lock=True)

    @staticmethod
    def user_in_tenant(session, *, tenant_id, user_id):
        return session.execute(text("SELECT id FROM users WHERE tenant_id=:tenant AND id=:user"), {
            "tenant": tenant_id, "user": user_id,
        }).scalar_one_or_none()

    @classmethod
    def insert(cls, session, command, authority, *, transition_type, prior_event, approved_by=None, approved_at=None):
        row = session.execute(text(f"""INSERT INTO reconciliation_window_governance_events(
            public_id,tenant_id,organization_unit_id,reconciliation_window_id,transition_type,prior_event_id,
            governed_revision_id,governed_revision_number,accounting_period_id,accounting_period_code,
            accounting_period_state,close_disposition,transition_reason,evidence_hash,evidence_payload,
            approved_by_user_id,approved_at,occurred_at,business_date,calendar_policy_version,correlation_id,
            causation_id,actor_user_id,actor_service,source_component,source_record_id,idempotency_scope,
            idempotency_key,request_fingerprint,metadata)
            VALUES(:public,:tenant,:org,:window,:transition,:prior,:revision,:revision_number,:period,:period_code,
            :period_state,:disposition,:reason,:evidence_hash,CAST(:evidence AS JSONB),:approved_by,:approved_at,
            :occurred,:business_date,:calendar,:correlation,:causation,:actor_user,:actor_service,:component,
            :record,:scope,:key,:fingerprint,CAST(:metadata AS JSONB)) RETURNING {cls.EVENT_COLUMNS}"""), {
            "public": str(command.public_id), "tenant": command.tenant_id, "org": command.organization_unit_id,
            "window": int(authority["window_id"]), "transition": transition_type,
            "prior": prior_event.id if prior_event else None, "revision": int(authority["revision_id"]),
            "revision_number": command.governed_revision_number, "period": int(authority["accounting_period_id"]),
            "period_code": authority["period_code"], "period_state": authority["period_state"],
            "disposition": getattr(command, "close_disposition", None), "reason": command.transition_reason,
            "evidence_hash": command.evidence_hash, "evidence": json.dumps(command.evidence_payload, sort_keys=True),
            "approved_by": approved_by, "approved_at": approved_at, "occurred": command.occurred_at,
            "business_date": command.business_date, "calendar": command.calendar_policy_version,
            "correlation": str(command.correlation_id), "causation": str(command.causation_id) if command.causation_id else None,
            "actor_user": command.actor_user_id, "actor_service": command.actor_service,
            "component": command.source_component, "record": command.source_record_id,
            "scope": command.idempotency_scope, "key": command.idempotency_key,
            "fingerprint": command.request_fingerprint, "metadata": json.dumps(command.metadata, sort_keys=True),
        }).mappings().one()
        return _event(row)

    @classmethod
    def history(cls, session, *, tenant_id, window_id):
        rows = session.execute(text(f"""SELECT {cls.EVENT_COLUMNS} FROM reconciliation_window_governance_events
            WHERE tenant_id=:tenant AND reconciliation_window_id=:window ORDER BY id"""), {
            "tenant": tenant_id, "window": window_id,
        }).mappings().all()
        return tuple(_event(row) for row in rows)
