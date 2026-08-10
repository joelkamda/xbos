"""SQL persistence and projections for M6.0 treasury balance authority."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text

from .operational_balance_contract import (
    CreateOperationalAccountCommand,
    RecordActualBalanceCommand,
    RecordBalanceAnchorCommand,
)


@dataclass(frozen=True)
class OperationalAccountRecord:
    id: int
    public_id: UUID
    tenant_id: int
    organization_unit_id: int
    parent_account_id: int | None
    account_class: str
    account_type: str
    code: str
    display_name: str
    currency_code: str
    aggregation_role: str
    reconciliation_enabled: bool
    active: bool
    opened_at: object
    closed_at: object | None
    request_fingerprint: str | None = None
    replayed: bool = False


@dataclass(frozen=True)
class BalanceAnchorRecord:
    id: int
    public_id: UUID
    operational_account_id: int
    anchor_balance: Decimal
    anchor_at: object
    provenance: str
    evidence_hash: str
    request_fingerprint: str
    replayed: bool = False


@dataclass(frozen=True)
class ActualBalanceRecord:
    id: int
    public_id: UUID
    operational_account_id: int
    actual_balance: Decimal
    observed_at: object
    provenance: str
    evidence_hash: str
    request_fingerprint: str
    replayed: bool = False


_ACCOUNT_COLUMNS = """a.id,a.public_id,a.tenant_id,a.organization_unit_id,a.parent_account_id,
a.account_class,a.account_type,a.code,a.display_name,a.currency_code,a.aggregation_role,
a.reconciliation_enabled,a.active,a.opened_at,a.closed_at"""


def _account(row, *, fingerprint=None, replayed=False) -> OperationalAccountRecord:
    return OperationalAccountRecord(
        int(row["id"]), UUID(str(row["public_id"])), int(row["tenant_id"]), int(row["organization_unit_id"]),
        int(row["parent_account_id"]) if row["parent_account_id"] is not None else None,
        row["account_class"], row["account_type"], row["code"], row["display_name"], row["currency_code"],
        row["aggregation_role"], bool(row["reconciliation_enabled"]), bool(row["active"]),
        row["opened_at"], row["closed_at"], fingerprint, replayed,
    )


class OperationalBalanceRepository:
    @staticmethod
    def account_by_public_id(session, *, tenant_id: int, public_id: UUID, lock: bool = False):
        locking = "FOR UPDATE OF a" if lock else ""
        row = session.execute(
            text(f"SELECT {_ACCOUNT_COLUMNS} FROM public.operational_financial_accounts a WHERE a.tenant_id=:tenant AND a.public_id=:public {locking}"),
            {"tenant": tenant_id, "public": str(public_id)},
        ).mappings().one_or_none()
        return _account(row) if row else None

    @staticmethod
    def account_by_idempotency(session, command: CreateOperationalAccountCommand):
        row = session.execute(text(f"""
            SELECT {_ACCOUNT_COLUMNS},auth.request_fingerprint
            FROM public.operational_account_authorities auth
            JOIN public.operational_financial_accounts a
              ON a.tenant_id=auth.tenant_id AND a.id=auth.operational_account_id
            WHERE auth.tenant_id=:tenant AND auth.idempotency_scope=:scope AND auth.idempotency_key=:key
        """), {"tenant": command.tenant_id, "scope": command.idempotency_scope, "key": command.idempotency_key}).mappings().one_or_none()
        return _account(row, fingerprint=row["request_fingerprint"], replayed=True) if row else None

    @classmethod
    def insert_account(cls, session, command: CreateOperationalAccountCommand, parent_id: int | None):
        row = session.execute(text("""
            INSERT INTO public.operational_financial_accounts(
              public_id,tenant_id,organization_unit_id,parent_account_id,account_class,account_type,
              code,display_name,currency_code,channel_code,external_account_mask,aggregation_role,
              reconciliation_enabled,active,opened_at,metadata)
            VALUES(:public,:tenant,:org,:parent,:class,:type,:code,:name,:currency,:channel,:mask,
                   :aggregation,:reconciliation,true,:opened,CAST(:metadata AS JSONB))
            RETURNING id,public_id,tenant_id,organization_unit_id,parent_account_id,account_class,
              account_type,code,display_name,currency_code,aggregation_role,reconciliation_enabled,
              active,opened_at,closed_at
        """), {
            "public": str(command.public_id), "tenant": command.tenant_id, "org": command.organization_unit_id,
            "parent": parent_id, "class": command.account_class, "type": command.account_type,
            "code": command.code, "name": command.display_name, "currency": command.currency_code,
            "channel": command.channel_code, "mask": command.external_account_mask,
            "aggregation": command.aggregation_role, "reconciliation": command.reconciliation_enabled,
            "opened": command.opened_at, "metadata": json.dumps(command.metadata, sort_keys=True),
        }).mappings().one()
        session.execute(text("""
            INSERT INTO public.operational_account_authorities(
              public_id,tenant_id,organization_unit_id,operational_account_id,source_component,
              source_record_id,idempotency_scope,idempotency_key,request_fingerprint,correlation_id,
              actor_user_id,actor_service,metadata)
            VALUES(:public,:tenant,:org,:account,:component,:record,:scope,:key,:fingerprint,:correlation,
                   :actor_user,:actor_service,CAST(:metadata AS JSONB))
        """), {
            "public": str(command.public_id), "tenant": command.tenant_id, "org": command.organization_unit_id,
            "account": int(row["id"]), "component": command.source_component, "record": command.source_record_id,
            "scope": command.idempotency_scope, "key": command.idempotency_key,
            "fingerprint": command.request_fingerprint, "correlation": str(command.correlation_id),
            "actor_user": command.actor_user_id, "actor_service": command.actor_service,
            "metadata": json.dumps(command.metadata, sort_keys=True),
        })
        return _account(row, fingerprint=command.request_fingerprint)

    @staticmethod
    def anchor_by_idempotency(session, command: RecordBalanceAnchorCommand):
        row = session.execute(text("""
            SELECT id,public_id,operational_account_id,anchor_balance,anchor_at,provenance,evidence_hash,request_fingerprint
            FROM public.operational_account_balance_anchors
            WHERE tenant_id=:tenant AND idempotency_scope=:scope AND idempotency_key=:key
        """), {"tenant": command.tenant_id, "scope": command.idempotency_scope, "key": command.idempotency_key}).mappings().one_or_none()
        return BalanceAnchorRecord(int(row["id"]), UUID(str(row["public_id"])), int(row["operational_account_id"]), Decimal(row["anchor_balance"]), row["anchor_at"], row["provenance"], row["evidence_hash"].strip(), row["request_fingerprint"].strip(), True) if row else None

    @staticmethod
    def account_has_anchor(session, *, tenant_id: int, account_id: int) -> bool:
        return bool(session.execute(text("SELECT 1 FROM public.operational_account_balance_anchors WHERE tenant_id=:tenant AND operational_account_id=:account"), {"tenant": tenant_id, "account": account_id}).scalar_one_or_none())

    @staticmethod
    def insert_anchor(session, command: RecordBalanceAnchorCommand, account_id: int):
        row = session.execute(text("""
            INSERT INTO public.operational_account_balance_anchors(
              public_id,tenant_id,organization_unit_id,operational_account_id,anchor_balance,currency_code,
              anchor_at,provenance,evidence_hash,evidence_payload,occurred_at,business_date,
              calendar_policy_version,correlation_id,actor_user_id,actor_service,source_component,
              source_record_id,idempotency_scope,idempotency_key,request_fingerprint,metadata)
            VALUES(:public,:tenant,:org,:account,:balance,:currency,:anchor_at,:provenance,:evidence_hash,
              CAST(:evidence AS JSONB),:occurred,:business_date,:calendar,:correlation,:actor_user,:actor_service,
              :component,:record,:scope,:key,:fingerprint,CAST(:metadata AS JSONB))
            RETURNING id,public_id,operational_account_id,anchor_balance,anchor_at,provenance,evidence_hash,request_fingerprint
        """), _balance_params(command, account_id, "anchor_balance", "anchor_at")).mappings().one()
        return BalanceAnchorRecord(int(row["id"]), UUID(str(row["public_id"])), int(row["operational_account_id"]), Decimal(row["anchor_balance"]), row["anchor_at"], row["provenance"], row["evidence_hash"].strip(), row["request_fingerprint"].strip())

    @staticmethod
    def actual_by_idempotency(session, command: RecordActualBalanceCommand):
        row = session.execute(text("""
            SELECT id,public_id,operational_account_id,actual_balance,observed_at,provenance,evidence_hash,request_fingerprint
            FROM public.operational_account_balance_observations
            WHERE tenant_id=:tenant AND idempotency_scope=:scope AND idempotency_key=:key
        """), {"tenant": command.tenant_id, "scope": command.idempotency_scope, "key": command.idempotency_key}).mappings().one_or_none()
        return ActualBalanceRecord(int(row["id"]), UUID(str(row["public_id"])), int(row["operational_account_id"]), Decimal(row["actual_balance"]), row["observed_at"], row["provenance"], row["evidence_hash"].strip(), row["request_fingerprint"].strip(), True) if row else None

    @staticmethod
    def insert_actual(session, command: RecordActualBalanceCommand, account_id: int):
        row = session.execute(text("""
            INSERT INTO public.operational_account_balance_observations(
              public_id,tenant_id,organization_unit_id,operational_account_id,actual_balance,currency_code,
              observed_at,provenance,evidence_hash,evidence_payload,occurred_at,business_date,
              calendar_policy_version,correlation_id,actor_user_id,actor_service,source_component,
              source_record_id,idempotency_scope,idempotency_key,request_fingerprint,metadata)
            VALUES(:public,:tenant,:org,:account,:balance,:currency,:observed_at,:provenance,:evidence_hash,
              CAST(:evidence AS JSONB),:occurred,:business_date,:calendar,:correlation,:actor_user,:actor_service,
              :component,:record,:scope,:key,:fingerprint,CAST(:metadata AS JSONB))
            RETURNING id,public_id,operational_account_id,actual_balance,observed_at,provenance,evidence_hash,request_fingerprint
        """), _balance_params(command, account_id, "actual_balance", "observed_at")).mappings().one()
        return ActualBalanceRecord(int(row["id"]), UUID(str(row["public_id"])), int(row["operational_account_id"]), Decimal(row["actual_balance"]), row["observed_at"], row["provenance"], row["evidence_hash"].strip(), row["request_fingerprint"].strip())

    @staticmethod
    def position(session, *, tenant_id: int, organization_unit_id: int, account_id: int, as_of):
        return session.execute(text("""
            WITH anchor AS (
              SELECT id,public_id,anchor_balance,anchor_at,provenance,evidence_hash
              FROM public.operational_account_balance_anchors
              WHERE tenant_id=:tenant AND operational_account_id=:account AND anchor_at<=:as_of
              ORDER BY anchor_at DESC,id DESC LIMIT 1
            ), movement AS (
              SELECT
                COALESCE(SUM(CASE WHEN target_operational_account_id=:account THEN amount ELSE 0 END),0) inflows,
                COALESCE(SUM(CASE WHEN source_operational_account_id=:account THEN amount ELSE 0 END),0) outflows
              FROM public.financial_events,anchor
              WHERE tenant_id=:tenant AND organization_unit_id=:org AND currency_code=(
                SELECT currency_code FROM public.operational_financial_accounts WHERE tenant_id=:tenant AND id=:account
              ) AND occurred_at>anchor.anchor_at AND occurred_at<=:as_of
                AND (source_operational_account_id=:account OR target_operational_account_id=:account)
            ), actual AS (
              SELECT id,public_id,actual_balance,observed_at,provenance,evidence_hash
              FROM public.operational_account_balance_observations
              WHERE tenant_id=:tenant AND operational_account_id=:account AND observed_at<=:as_of
              ORDER BY observed_at DESC,id DESC LIMIT 1
            )
            SELECT anchor.id anchor_id,anchor.public_id anchor_public_id,anchor.anchor_balance,anchor.anchor_at,
                   anchor.provenance anchor_provenance,anchor.evidence_hash anchor_evidence_hash,
                   movement.inflows,movement.outflows,
                   anchor.anchor_balance+movement.inflows-movement.outflows expected_balance,
                   actual.id actual_id,actual.public_id actual_public_id,actual.actual_balance,actual.observed_at,
                   actual.provenance actual_provenance,actual.evidence_hash actual_evidence_hash,
                   CASE WHEN actual.id IS NULL THEN NULL
                        ELSE actual.actual_balance-(anchor.anchor_balance+movement.inflows-movement.outflows) END variance
            FROM anchor CROSS JOIN movement LEFT JOIN actual ON TRUE
        """), {"tenant": tenant_id, "org": organization_unit_id, "account": account_id, "as_of": as_of}).mappings().one_or_none()


def _balance_params(command, account_id: int, amount_field: str, time_field: str):
    return {
        "public": str(command.public_id), "tenant": command.tenant_id, "org": command.organization_unit_id,
        "account": account_id, "balance": getattr(command, amount_field), "currency": command.currency_code,
        time_field: getattr(command, time_field), "provenance": command.provenance,
        "evidence_hash": command.evidence_hash, "evidence": json.dumps(command.evidence_payload, sort_keys=True),
        "occurred": command.occurred_at, "business_date": command.business_date,
        "calendar": command.calendar_policy_version, "correlation": str(command.correlation_id),
        "actor_user": command.actor_user_id, "actor_service": command.actor_service,
        "component": command.source_component, "record": command.source_record_id,
        "scope": command.idempotency_scope, "key": command.idempotency_key,
        "fingerprint": command.request_fingerprint, "metadata": json.dumps(command.metadata, sort_keys=True),
    }
