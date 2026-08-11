"""Persistence and canonical-position adapters for M6.4 controls."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text


@dataclass(frozen=True)
class CanonicalPosition:
    opening: Decimal
    increases: Decimal
    decreases: Decimal
    adjustments: Decimal
    closing: Decimal


@dataclass(frozen=True)
class ReconciliationControlRecord:
    id: int
    public_id: UUID
    tenant_id: int
    organization_unit_id: int
    control_type: str
    operational_account_id: int | None
    party_id: UUID | None
    currency_code: str
    canonical_opening: Decimal
    canonical_increases: Decimal
    canonical_decreases: Decimal
    canonical_adjustments: Decimal
    canonical_closing: Decimal
    control_position: Decimal
    explained_amount: Decimal
    raw_variance: Decimal
    unexplained_variance: Decimal
    reconciliation_status: str
    revision_number: int
    supersedes_control_id: int | None
    semantic_fingerprint: str
    request_fingerprint: str
    replayed: bool = False


def _record(row, replayed=False):
    return ReconciliationControlRecord(
        int(row["id"]), UUID(str(row["public_id"])), int(row["tenant_id"]), int(row["organization_unit_id"]),
        row["control_type"], int(row["operational_account_id"]) if row["operational_account_id"] is not None else None,
        UUID(str(row["party_id"])) if row["party_id"] is not None else None, row["currency_code"],
        *[Decimal(row[name]) for name in ("canonical_opening","canonical_increases","canonical_decreases",
          "canonical_adjustments","canonical_closing","control_position","explained_amount","raw_variance","unexplained_variance")],
        row["reconciliation_status"], int(row["revision_number"]),
        int(row["supersedes_control_id"]) if row["supersedes_control_id"] is not None else None,
        row["semantic_fingerprint"].strip(), row["request_fingerprint"].strip(), replayed,
    )


class ReconciliationControlRepository:
    COLUMNS = """id,public_id,tenant_id,organization_unit_id,control_type,operational_account_id,party_id,
currency_code,canonical_opening,canonical_increases,canonical_decreases,canonical_adjustments,canonical_closing,
control_position,explained_amount,raw_variance,unexplained_variance,reconciliation_status,revision_number,
supersedes_control_id,semantic_fingerprint,request_fingerprint"""

    @classmethod
    def by_idempotency(cls, session, command):
        row = session.execute(text(f"SELECT {cls.COLUMNS} FROM reconciliation_controls WHERE tenant_id=:tenant AND idempotency_scope=:scope AND idempotency_key=:key FOR UPDATE"),
            {"tenant": command.tenant_id, "scope": command.idempotency_scope, "key": command.idempotency_key}).mappings().one_or_none()
        return _record(row, True) if row else None

    @staticmethod
    def resolve_period(session, command):
        if not command.accounting_period_code:
            return None
        return session.execute(text("""SELECT id,period_code,period_start,period_end,period_state FROM accounting_periods
            WHERE tenant_id=:tenant AND legal_entity_unit_id=:org AND period_code=:code"""),
            {"tenant": command.tenant_id, "org": command.organization_unit_id, "code": command.accounting_period_code}).mappings().one_or_none()

    @staticmethod
    def bank_authority(session, command):
        return session.execute(text("""SELECT a.id account_id,a.organization_unit_id,a.currency_code,a.reconciliation_enabled,
            w.id window_id,w.window_start,w.window_end,r.id revision_id,r.revision_number,
            COALESCE(g.governance_state,'open') governance_state
          FROM operational_financial_accounts a
          JOIN reconciliation_series s ON s.tenant_id=a.tenant_id AND s.operational_account_id=a.id
          JOIN reconciliation_windows w ON w.tenant_id=s.tenant_id AND w.reconciliation_series_id=s.id
          JOIN current_reconciliation_window_revisions r ON r.tenant_id=w.tenant_id AND r.reconciliation_window_id=w.id
          LEFT JOIN current_reconciliation_window_governance g ON g.tenant_id=w.tenant_id AND g.reconciliation_window_id=w.id
          WHERE a.tenant_id=:tenant AND a.public_id=:account AND w.public_id=:window FOR UPDATE OF a,w"""),
          {"tenant": command.tenant_id, "account": str(command.operational_account_public_id),
           "window": str(command.reconciliation_window_public_id)}).mappings().one_or_none()

    @staticmethod
    def bank_position(session, command, authority):
        row = session.execute(text("""WITH anchor AS (
          SELECT anchor_balance,anchor_at FROM operational_account_balance_anchors
          WHERE tenant_id=:tenant AND operational_account_id=:account AND anchor_at<=:start
          ORDER BY anchor_at DESC,id DESC LIMIT 1
        ), before_move AS (
          SELECT COALESCE(SUM(CASE WHEN target_operational_account_id=:account THEN amount ELSE -amount END),0) amount
          FROM financial_events,anchor WHERE tenant_id=:tenant AND organization_unit_id=:org
            AND currency_code=:currency AND occurred_at>anchor.anchor_at AND occurred_at<=:start
            AND (source_operational_account_id=:account OR target_operational_account_id=:account)
        ), period_move AS (
          SELECT COALESCE(SUM(CASE WHEN target_operational_account_id=:account THEN amount ELSE 0 END),0) inflows,
                 COALESCE(SUM(CASE WHEN source_operational_account_id=:account THEN amount ELSE 0 END),0) outflows
          FROM financial_events WHERE tenant_id=:tenant AND organization_unit_id=:org AND currency_code=:currency
            AND occurred_at>:start AND occurred_at<=:as_of
            AND (source_operational_account_id=:account OR target_operational_account_id=:account)
        ) SELECT anchor.anchor_balance+before_move.amount opening,period_move.inflows increases,
                 period_move.outflows decreases,0::numeric adjustments,
                 anchor.anchor_balance+before_move.amount+period_move.inflows-period_move.outflows closing
          FROM anchor CROSS JOIN before_move CROSS JOIN period_move"""), {
          "tenant": command.tenant_id, "org": command.organization_unit_id, "account": int(authority["account_id"]),
          "currency": command.currency_code, "start": command.period_start, "as_of": command.as_of,
        }).mappings().one_or_none()
        return _position(row)

    @staticmethod
    def party_position(session, command):
        receivable = command.control_type == "accounts_receivable"
        party_column = "debtor_party_id" if receivable else "creditor_party_id"
        types = "('trade_receivable','customer_receivable')" if receivable else "('trade_payable','supplier_payable','expense_payable')"
        row = session.execute(text(f"""WITH obligations AS (
          SELECT o.id,o.original_amount,o.occurred_at FROM financial_obligations o
          WHERE o.tenant_id=:tenant AND o.organization_unit_id=:org AND o.currency_code=:currency
            AND o.{party_column}=:party AND o.obligation_type IN {types} AND o.occurred_at<=:as_of
            AND o.obligation_state NOT IN('cancelled','written_off')
        ), allocations AS (
          SELECT pa.id,pa.obligation_id,pa.allocation_amount,pa.occurred_at FROM payment_allocations pa
          JOIN obligations o ON o.id=pa.obligation_id WHERE pa.tenant_id=:tenant AND pa.occurred_at<=:as_of
        ), reversals AS (
          SELECT ar.payment_allocation_id,ar.reversal_amount,ar.occurred_at FROM allocation_reversals ar
          JOIN allocations a ON a.id=ar.payment_allocation_id WHERE ar.tenant_id=:tenant AND ar.occurred_at<=:as_of
        ) SELECT
          COALESCE((SELECT SUM(original_amount) FROM obligations WHERE occurred_at<=:start),0)
            -COALESCE((SELECT SUM(allocation_amount) FROM allocations WHERE occurred_at<=:start),0)
            +COALESCE((SELECT SUM(reversal_amount) FROM reversals WHERE occurred_at<=:start),0) opening,
          COALESCE((SELECT SUM(original_amount) FROM obligations WHERE occurred_at>:start),0)
            +COALESCE((SELECT SUM(reversal_amount) FROM reversals WHERE occurred_at>:start),0) increases,
          COALESCE((SELECT SUM(allocation_amount) FROM allocations WHERE occurred_at>:start),0) decreases,
          0::numeric adjustments,
          COALESCE((SELECT SUM(original_amount) FROM obligations),0)
            -COALESCE((SELECT SUM(allocation_amount) FROM allocations),0)
            +COALESCE((SELECT SUM(reversal_amount) FROM reversals),0) closing"""), {
          "tenant": command.tenant_id, "org": command.organization_unit_id, "currency": command.currency_code,
          "party": str(command.party_id), "start": command.period_start, "as_of": command.as_of,
        }).mappings().one()
        return _position(row)

    @staticmethod
    def latest(session, command):
        return session.execute(text("""SELECT id,revision_number FROM reconciliation_controls
          WHERE tenant_id=:tenant AND organization_unit_id=:org AND control_type=:type
            AND COALESCE(operational_account_id,0)=COALESCE(:account,0)
            AND COALESCE(party_id,'00000000-0000-0000-0000-000000000000'::uuid)=COALESCE(CAST(:party AS uuid),'00000000-0000-0000-0000-000000000000'::uuid)
            AND currency_code=:currency AND period_start=:start AND period_end=:end
          ORDER BY revision_number DESC LIMIT 1 FOR UPDATE"""), {
          "tenant": command.tenant_id, "org": command.organization_unit_id, "type": command.control_type,
          "account": session.execute(text("SELECT id FROM operational_financial_accounts WHERE tenant_id=:tenant AND public_id=:public"),
              {"tenant": command.tenant_id, "public": str(command.operational_account_public_id)}).scalar_one_or_none()
              if command.operational_account_public_id else None,
          "party": str(command.party_id) if command.party_id else None,
          "currency": command.currency_code, "start": command.period_start, "end": command.period_end,
        }).mappings().one_or_none()

    @classmethod
    def insert(cls, session, command, position, authority, period, latest, semantic, explained, raw, unexplained, status):
        account_id = int(authority["account_id"]) if authority else None
        values = {"public": str(command.public_id), "tenant": command.tenant_id, "org": command.organization_unit_id,
          "type": command.control_type, "account": account_id, "party": str(command.party_id) if command.party_id else None,
          "window": int(authority["window_id"]) if authority else None, "period": int(period["id"]) if period else None,
          "currency": command.currency_code, "start": command.period_start, "end": command.period_end, "as_of": command.as_of,
          "opening": position.opening, "increases": position.increases, "decreases": position.decreases,
          "adjustments": position.adjustments, "closing": position.closing, "control": command.control_position,
          "explained": explained, "raw": raw, "unexplained": unexplained, "status": status,
          "revision": int(latest["revision_number"])+1 if latest else 1, "supersedes": int(latest["id"]) if latest else None,
          "window_revision": int(authority["revision_id"]) if authority else None,
          "window_revision_number": int(authority["revision_number"]) if authority else None,
          "governance": authority["governance_state"] if authority else None, "occurred": command.occurred_at,
          "business_date": command.business_date, "calendar": command.calendar_policy_version,
          "correlation": str(command.correlation_id), "causation": str(command.causation_id) if command.causation_id else None,
          "actor_user": command.actor_user_id, "actor_service": command.actor_service, "component": command.source_component,
          "record": command.source_record_id, "scope": command.idempotency_scope, "key": command.idempotency_key,
          "fingerprint": command.request_fingerprint, "semantic": semantic, "metadata": json.dumps(command.metadata,sort_keys=True)}
        row = session.execute(text(f"""INSERT INTO reconciliation_controls(public_id,tenant_id,organization_unit_id,
          control_type,operational_account_id,party_id,reconciliation_window_id,accounting_period_id,currency_code,
          period_start,period_end,as_of,canonical_opening,canonical_increases,canonical_decreases,canonical_adjustments,
          canonical_closing,control_position,explained_amount,raw_variance,unexplained_variance,reconciliation_status,
          revision_number,supersedes_control_id,governed_window_revision_id,governed_window_revision_number,
          window_governance_state,occurred_at,business_date,calendar_policy_version,correlation_id,causation_id,
          actor_user_id,actor_service,source_component,source_record_id,idempotency_scope,idempotency_key,
          request_fingerprint,semantic_fingerprint,metadata) VALUES(:public,:tenant,:org,:type,:account,CAST(:party AS uuid),
          :window,:period,:currency,:start,:end,:as_of,:opening,:increases,:decreases,:adjustments,:closing,:control,
          :explained,:raw,:unexplained,:status,:revision,:supersedes,:window_revision,:window_revision_number,:governance,
          :occurred,:business_date,:calendar,:correlation,:causation,:actor_user,:actor_service,:component,:record,:scope,
          :key,:fingerprint,:semantic,CAST(:metadata AS jsonb)) RETURNING {cls.COLUMNS}"""), values).mappings().one()
        control_id = int(row["id"])
        for index, item in enumerate(command.explanations, 1):
            session.execute(text("""INSERT INTO reconciliation_control_items(public_id,tenant_id,reconciliation_control_id,
              sequence_number,item_type,amount,canonical_reference_type,canonical_reference_public_id,explanation,
              evidence_reference,metadata) VALUES(:public,:tenant,:control,:sequence,:type,:amount,:reference_type,
              :reference_public,:explanation,:evidence,CAST(:metadata AS jsonb))"""), {
              "public": str(item.public_id), "tenant": command.tenant_id, "control": control_id, "sequence": index,
              "type": item.item_type, "amount": item.amount, "reference_type": item.canonical_reference_type,
              "reference_public": str(item.canonical_reference_public_id) if item.canonical_reference_public_id else None,
              "explanation": item.explanation, "evidence": item.evidence_reference,
              "metadata": json.dumps(item.metadata,sort_keys=True)})
        for index, evidence in enumerate(command.evidence, 1):
            session.execute(text("""INSERT INTO reconciliation_evidence_references(public_id,tenant_id,
              reconciliation_control_id,sequence_number,evidence_type,external_reference,evidence_source,observed_at,
              evidence_hash,actor_user_id,actor_service,source_component,metadata) VALUES(:public,:tenant,:control,
              :sequence,:type,:reference,:source,:observed,:hash,:actor_user,:actor_service,:component,CAST(:metadata AS jsonb))"""), {
              "public": str(evidence.public_id), "tenant": command.tenant_id, "control": control_id, "sequence": index,
              "type": evidence.evidence_type, "reference": evidence.external_reference, "source": evidence.evidence_source,
              "observed": evidence.observed_at, "hash": evidence.evidence_hash, "actor_user": command.actor_user_id,
              "actor_service": command.actor_service, "component": command.source_component,
              "metadata": json.dumps(evidence.metadata,sort_keys=True)})
        return _record(row)

    @classmethod
    def by_public_id(cls, session, tenant_id, public_id):
        row = session.execute(text(f"SELECT {cls.COLUMNS} FROM reconciliation_controls WHERE tenant_id=:tenant AND public_id=:public"),
          {"tenant": tenant_id,"public":str(public_id)}).mappings().one_or_none()
        return _record(row) if row else None

    @staticmethod
    def report_rows(session, tenant_id, control_id):
        items = session.execute(text("SELECT sequence_number,item_type,amount,explanation,evidence_reference FROM reconciliation_control_items WHERE tenant_id=:tenant AND reconciliation_control_id=:id ORDER BY sequence_number,id"), {"tenant":tenant_id,"id":control_id}).mappings().all()
        evidence = session.execute(text("SELECT sequence_number,evidence_type,external_reference,evidence_source,observed_at,evidence_hash FROM reconciliation_evidence_references WHERE tenant_id=:tenant AND reconciliation_control_id=:id ORDER BY sequence_number,id"), {"tenant":tenant_id,"id":control_id}).mappings().all()
        return items,evidence


def _position(row):
    if row is None:
        return None
    return CanonicalPosition(*(Decimal(row[name]) for name in ("opening","increases","decreases","adjustments","closing")))
