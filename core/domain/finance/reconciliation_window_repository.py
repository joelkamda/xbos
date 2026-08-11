"""Persistence for M6.2 reconciliation calendars, windows, and cascades."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import time
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text


@dataclass(frozen=True)
class CalendarPolicyRecord:
    id: int
    public_id: UUID
    tenant_id: int
    organization_unit_id: int
    policy_code: str
    policy_version: int
    timezone_name: str
    business_day_boundary: time
    shifts: tuple[dict, ...]
    effective_from: object
    request_fingerprint: str
    replayed: bool = False


@dataclass(frozen=True)
class ReconciliationSeriesRecord:
    id: int
    public_id: UUID
    tenant_id: int
    organization_unit_id: int
    operational_account_id: int
    operational_account_public_id: UUID
    calendar_policy_id: int
    calendar_policy_version: int
    series_code: str
    currency_code: str
    starts_at: object
    request_fingerprint: str
    replayed: bool = False


@dataclass(frozen=True)
class ReconciliationWindowRecord:
    id: int
    public_id: UUID
    tenant_id: int
    organization_unit_id: int
    reconciliation_series_id: int
    predecessor_window_id: int | None
    window_start: object
    window_end: object
    business_date: object
    shift_code: str
    request_fingerprint: str
    replayed: bool = False


@dataclass(frozen=True)
class ReconciliationWindowRevisionRecord:
    id: int
    public_id: UUID
    window_id: int
    revision_number: int
    revision_reason: str
    opening_expected: Decimal
    closing_expected: Decimal
    actual_closing: Decimal | None
    variance: Decimal | None
    readiness_condition: str
    actual_observation_id: int | None
    supersedes_revision_id: int | None
    cascade_run_id: int | None


@dataclass(frozen=True)
class CascadeRunRecord:
    id: int
    public_id: UUID
    request_fingerprint: str
    replayed: bool


def _policy(row, *, replayed=False):
    return CalendarPolicyRecord(
        int(row["id"]), UUID(str(row["public_id"])), int(row["tenant_id"]), int(row["organization_unit_id"]),
        row["policy_code"], int(row["policy_version"]), row["timezone_name"], row["business_day_boundary"],
        tuple(row["shift_definitions"]), row["effective_from"], row["request_fingerprint"].strip(), replayed,
    )


def _series(row, *, replayed=False):
    return ReconciliationSeriesRecord(
        int(row["id"]), UUID(str(row["public_id"])), int(row["tenant_id"]), int(row["organization_unit_id"]),
        int(row["operational_account_id"]), UUID(str(row["operational_account_public_id"])),
        int(row["calendar_policy_id"]), int(row["calendar_policy_version"]),
        row["series_code"], row["currency_code"], row["starts_at"],
        row["request_fingerprint"].strip(), replayed,
    )


def _window(row, *, replayed=False):
    return ReconciliationWindowRecord(
        int(row["id"]), UUID(str(row["public_id"])), int(row["tenant_id"]), int(row["organization_unit_id"]),
        int(row["reconciliation_series_id"]), int(row["predecessor_window_id"]) if row["predecessor_window_id"] is not None else None,
        row["window_start"], row["window_end"], row["business_date"], row["shift_code"],
        row["request_fingerprint"].strip(), replayed,
    )


def _revision(row):
    return ReconciliationWindowRevisionRecord(
        int(row["id"]), UUID(str(row["public_id"])), int(row["reconciliation_window_id"]), int(row["revision_number"]),
        row["revision_reason"], Decimal(row["opening_expected"]), Decimal(row["closing_expected"]),
        Decimal(row["actual_closing"]) if row["actual_closing"] is not None else None,
        Decimal(row["variance"]) if row["variance"] is not None else None, row["readiness_condition"],
        int(row["actual_observation_id"]) if row["actual_observation_id"] is not None else None,
        int(row["supersedes_revision_id"]) if row["supersedes_revision_id"] is not None else None,
        int(row["cascade_run_id"]) if row["cascade_run_id"] is not None else None,
    )


class ReconciliationWindowRepository:
    POLICY_COLUMNS = """id,public_id,tenant_id,organization_unit_id,policy_code,policy_version,timezone_name,
business_day_boundary,shift_definitions,effective_from,request_fingerprint"""
    SERIES_COLUMNS = """s.id,s.public_id,s.tenant_id,s.organization_unit_id,s.operational_account_id,
a.public_id operational_account_public_id,s.calendar_policy_id,p.policy_version calendar_policy_version,
s.series_code,s.currency_code,s.starts_at,s.request_fingerprint"""
    WINDOW_COLUMNS = """id,public_id,tenant_id,organization_unit_id,reconciliation_series_id,predecessor_window_id,
window_start,window_end,business_date,shift_code,request_fingerprint"""

    @classmethod
    def policy_by_idempotency(cls, session, command):
        row = session.execute(text(f"SELECT {cls.POLICY_COLUMNS} FROM reconciliation_calendar_policies WHERE tenant_id=:tenant AND idempotency_scope=:scope AND idempotency_key=:key FOR UPDATE"), {
            "tenant": command.tenant_id, "scope": command.idempotency_scope, "key": command.idempotency_key,
        }).mappings().one_or_none()
        return _policy(row, replayed=True) if row else None

    @classmethod
    def insert_policy(cls, session, command):
        row = session.execute(text(f"""INSERT INTO reconciliation_calendar_policies(
            public_id,tenant_id,organization_unit_id,policy_code,policy_version,timezone_name,business_day_boundary,
            shift_definitions,effective_from,occurred_at,business_date,calendar_policy_version,correlation_id,causation_id,
            actor_user_id,actor_service,source_component,source_record_id,idempotency_scope,idempotency_key,request_fingerprint,metadata)
            VALUES(:public,:tenant,:org,:code,:version,:timezone,:boundary,CAST(:shifts AS JSONB),:effective,:occurred,
            :business_date,:calendar,:correlation,:causation,:actor_user,:actor_service,:component,:record,:scope,:key,
            :fingerprint,CAST(:metadata AS JSONB)) RETURNING {cls.POLICY_COLUMNS}"""), {
            "public": str(command.public_id), "tenant": command.tenant_id, "org": command.organization_unit_id,
            "code": command.policy_code, "version": command.policy_version, "timezone": command.timezone_name,
            "boundary": command.business_day_boundary, "shifts": json.dumps([item.canonical_payload() for item in command.shifts]),
            "effective": command.effective_from, "occurred": command.occurred_at, "business_date": command.business_date,
            "calendar": command.calendar_policy_version, "correlation": str(command.correlation_id),
            "causation": str(command.causation_id) if command.causation_id else None, "actor_user": command.actor_user_id,
            "actor_service": command.actor_service, "component": command.source_component, "record": command.source_record_id,
            "scope": command.idempotency_scope, "key": command.idempotency_key, "fingerprint": command.request_fingerprint,
            "metadata": json.dumps(command.metadata, sort_keys=True),
        }).mappings().one()
        return _policy(row)

    @classmethod
    def policy_by_public_id(cls, session, *, tenant_id, public_id, lock=False):
        locking = "FOR UPDATE" if lock else ""
        row = session.execute(text(f"SELECT {cls.POLICY_COLUMNS} FROM reconciliation_calendar_policies WHERE tenant_id=:tenant AND public_id=:public {locking}"), {
            "tenant": tenant_id, "public": str(public_id),
        }).mappings().one_or_none()
        return _policy(row) if row else None

    @classmethod
    def series_by_idempotency(cls, session, command):
        row = session.execute(text(f"""SELECT {cls.SERIES_COLUMNS} FROM reconciliation_series s
            JOIN operational_financial_accounts a ON a.tenant_id=s.tenant_id AND a.id=s.operational_account_id
            JOIN reconciliation_calendar_policies p ON p.tenant_id=s.tenant_id AND p.id=s.calendar_policy_id
            WHERE s.tenant_id=:tenant AND s.idempotency_scope=:scope AND s.idempotency_key=:key FOR UPDATE OF s"""), {
            "tenant": command.tenant_id, "scope": command.idempotency_scope, "key": command.idempotency_key,
        }).mappings().one_or_none()
        return _series(row, replayed=True) if row else None

    @classmethod
    def insert_series(cls, session, command, account_id, policy_id):
        row = session.execute(text(f"""INSERT INTO reconciliation_series(
            public_id,tenant_id,organization_unit_id,operational_account_id,calendar_policy_id,series_code,currency_code,
            starts_at,occurred_at,business_date,calendar_policy_version,correlation_id,causation_id,actor_user_id,actor_service,
            source_component,source_record_id,idempotency_scope,idempotency_key,request_fingerprint,metadata)
            VALUES(:public,:tenant,:org,:account,:policy,:code,:currency,:starts,:occurred,:business_date,:calendar,
            :correlation,:causation,:actor_user,:actor_service,:component,:record,:scope,:key,:fingerprint,CAST(:metadata AS JSONB))
            RETURNING id"""), {
            "public": str(command.public_id), "tenant": command.tenant_id, "org": command.organization_unit_id,
            "account": account_id, "policy": policy_id, "code": command.series_code, "currency": command.currency_code,
            "starts": command.starts_at, "occurred": command.occurred_at, "business_date": command.business_date,
            "calendar": command.calendar_policy_version, "correlation": str(command.correlation_id),
            "causation": str(command.causation_id) if command.causation_id else None, "actor_user": command.actor_user_id,
            "actor_service": command.actor_service, "component": command.source_component, "record": command.source_record_id,
            "scope": command.idempotency_scope, "key": command.idempotency_key, "fingerprint": command.request_fingerprint,
            "metadata": json.dumps(command.metadata, sort_keys=True),
        }).scalar_one()
        return cls.series_by_id(session, tenant_id=command.tenant_id, series_id=int(row), lock=False)

    @classmethod
    def series_by_public_id(cls, session, *, tenant_id, public_id, lock=False):
        locking = "FOR UPDATE OF s" if lock else ""
        row = session.execute(text(f"""SELECT {cls.SERIES_COLUMNS} FROM reconciliation_series s
            JOIN operational_financial_accounts a ON a.tenant_id=s.tenant_id AND a.id=s.operational_account_id
            JOIN reconciliation_calendar_policies p ON p.tenant_id=s.tenant_id AND p.id=s.calendar_policy_id
            WHERE s.tenant_id=:tenant AND s.public_id=:public {locking}"""), {
            "tenant": tenant_id, "public": str(public_id),
        }).mappings().one_or_none()
        return _series(row) if row else None

    @classmethod
    def series_by_id(cls, session, *, tenant_id, series_id, lock=False):
        locking = "FOR UPDATE OF s" if lock else ""
        row = session.execute(text(f"""SELECT {cls.SERIES_COLUMNS} FROM reconciliation_series s
            JOIN operational_financial_accounts a ON a.tenant_id=s.tenant_id AND a.id=s.operational_account_id
            JOIN reconciliation_calendar_policies p ON p.tenant_id=s.tenant_id AND p.id=s.calendar_policy_id
            WHERE s.tenant_id=:tenant AND s.id=:series {locking}"""), {"tenant": tenant_id, "series": series_id}).mappings().one_or_none()
        return _series(row) if row else None

    @classmethod
    def window_by_idempotency(cls, session, command):
        row = session.execute(text(f"SELECT {cls.WINDOW_COLUMNS} FROM reconciliation_windows WHERE tenant_id=:tenant AND idempotency_scope=:scope AND idempotency_key=:key FOR UPDATE"), {
            "tenant": command.tenant_id, "scope": command.idempotency_scope, "key": command.idempotency_key,
        }).mappings().one_or_none()
        return _window(row, replayed=True) if row else None

    @classmethod
    def latest_window(cls, session, *, tenant_id, series_id, lock=False):
        locking = "FOR UPDATE" if lock else ""
        row = session.execute(text(f"""SELECT {cls.WINDOW_COLUMNS} FROM reconciliation_windows
            WHERE tenant_id=:tenant AND reconciliation_series_id=:series ORDER BY window_start DESC,id DESC LIMIT 1 {locking}"""), {
            "tenant": tenant_id, "series": series_id,
        }).mappings().one_or_none()
        return _window(row) if row else None

    @classmethod
    def insert_window(cls, session, command, series, predecessor, *, business_date, shift_code):
        row = session.execute(text(f"""INSERT INTO reconciliation_windows(
            public_id,tenant_id,organization_unit_id,reconciliation_series_id,predecessor_window_id,window_start,window_end,
            business_date,shift_code,calendar_policy_version,evidence_hash,evidence_payload,occurred_at,correlation_id,
            causation_id,actor_user_id,actor_service,source_component,source_record_id,idempotency_scope,idempotency_key,
            request_fingerprint,metadata)
            VALUES(:public,:tenant,:org,:series,:predecessor,:window_start,:window_end,:business_date,:shift_code,:calendar,
            :evidence_hash,CAST(:evidence AS JSONB),:occurred,:correlation,:causation,:actor_user,:actor_service,:component,
            :record,:scope,:key,:fingerprint,CAST(:metadata AS JSONB)) RETURNING {cls.WINDOW_COLUMNS}"""), {
            "public": str(command.public_id), "tenant": command.tenant_id, "org": command.organization_unit_id,
            "series": series.id, "predecessor": predecessor.id if predecessor else None,
            "window_start": command.window_start, "window_end": command.window_end, "business_date": business_date,
            "shift_code": shift_code, "calendar": command.calendar_policy_version, "evidence_hash": command.evidence_hash,
            "evidence": json.dumps(command.evidence_payload, sort_keys=True), "occurred": command.occurred_at,
            "correlation": str(command.correlation_id), "causation": str(command.causation_id) if command.causation_id else None,
            "actor_user": command.actor_user_id, "actor_service": command.actor_service, "component": command.source_component,
            "record": command.source_record_id, "scope": command.idempotency_scope, "key": command.idempotency_key,
            "fingerprint": command.request_fingerprint, "metadata": json.dumps(command.metadata, sort_keys=True),
        }).mappings().one()
        return _window(row)

    @staticmethod
    def actual_in_window(session, *, tenant_id, account_id, window_start, window_end):
        return session.execute(text("""SELECT id,actual_balance,observed_at,provenance,evidence_hash
            FROM operational_account_balance_observations
            WHERE tenant_id=:tenant AND operational_account_id=:account
              AND observed_at>:window_start AND observed_at<=:window_end
            ORDER BY observed_at DESC,id DESC LIMIT 1"""), {
            "tenant": tenant_id, "account": account_id, "window_start": window_start, "window_end": window_end,
        }).mappings().one_or_none()

    @staticmethod
    def insert_revision(session, *, public_id, tenant_id, organization_unit_id, window_id, revision_number,
                        revision_reason, projection, actual, supersedes_revision_id=None, cascade_run_id=None,
                        correlation_id, causation_id, actor_user_id, actor_service, source_component, source_record_id,
                        metadata):
        actual_amount = Decimal(actual["actual_balance"]) if actual else None
        closing = Decimal(projection["closing_expected"])
        row = session.execute(text("""INSERT INTO reconciliation_window_revisions(
            public_id,tenant_id,organization_unit_id,reconciliation_window_id,revision_number,revision_reason,
            opening_expected,closing_expected,actual_closing,variance,readiness_condition,actual_observation_id,
            supersedes_revision_id,cascade_run_id,correlation_id,causation_id,actor_user_id,actor_service,
            source_component,source_record_id,metadata)
            VALUES(:public,:tenant,:org,:window,:revision,:reason,:opening,:closing,:actual,:variance,:readiness,
            :observation,:supersedes,:cascade,:correlation,:causation,:actor_user,:actor_service,:component,:record,
            CAST(:metadata AS JSONB)) RETURNING *"""), {
            "public": str(public_id), "tenant": tenant_id, "org": organization_unit_id, "window": window_id,
            "revision": revision_number, "reason": revision_reason, "opening": projection["opening_expected"],
            "closing": closing, "actual": actual_amount, "variance": actual_amount-closing if actual_amount is not None else None,
            "readiness": "ready" if actual else "awaiting_actual", "observation": int(actual["id"]) if actual else None,
            "supersedes": supersedes_revision_id, "cascade": cascade_run_id, "correlation": str(correlation_id),
            "causation": str(causation_id) if causation_id else None, "actor_user": actor_user_id,
            "actor_service": actor_service, "component": source_component, "record": source_record_id,
            "metadata": json.dumps(metadata, sort_keys=True),
        }).mappings().one()
        return _revision(row)

    @staticmethod
    def current_revision(session, *, tenant_id, window_id, lock=False):
        locking = "FOR UPDATE" if lock else ""
        row = session.execute(text(f"""SELECT * FROM reconciliation_window_revisions
            WHERE tenant_id=:tenant AND reconciliation_window_id=:window ORDER BY revision_number DESC LIMIT 1 {locking}"""), {
            "tenant": tenant_id, "window": window_id,
        }).mappings().one_or_none()
        return _revision(row) if row else None

    @staticmethod
    def revision_by_number(session, *, tenant_id, window_id, revision_number):
        row = session.execute(text("""SELECT * FROM reconciliation_window_revisions
            WHERE tenant_id=:tenant AND reconciliation_window_id=:window AND revision_number=:revision"""), {
            "tenant": tenant_id, "window": window_id, "revision": revision_number,
        }).mappings().one_or_none()
        return _revision(row) if row else None

    @staticmethod
    def windows_from(session, *, tenant_id, series_id, changed_from_at):
        return session.execute(text("""SELECT id,public_id,window_start,window_end FROM reconciliation_windows
            WHERE tenant_id=:tenant AND reconciliation_series_id=:series AND window_end>=:changed
            ORDER BY window_start,id FOR UPDATE"""), {
            "tenant": tenant_id, "series": series_id, "changed": changed_from_at,
        }).mappings().all()

    @staticmethod
    def cascade_by_idempotency(session, command):
        row = session.execute(text("""SELECT id,public_id,request_fingerprint FROM reconciliation_cascade_runs
            WHERE tenant_id=:tenant AND idempotency_scope=:scope AND idempotency_key=:key FOR UPDATE"""), {
            "tenant": command.tenant_id, "scope": command.idempotency_scope, "key": command.idempotency_key,
        }).mappings().one_or_none()
        return CascadeRunRecord(int(row["id"]), UUID(str(row["public_id"])), row["request_fingerprint"].strip(), True) if row else None

    @staticmethod
    def insert_cascade(session, command, series_id):
        row = session.execute(text("""INSERT INTO reconciliation_cascade_runs(
            public_id,tenant_id,organization_unit_id,reconciliation_series_id,changed_from_at,cascade_reason,
            evidence_hash,evidence_payload,occurred_at,business_date,calendar_policy_version,correlation_id,causation_id,
            actor_user_id,actor_service,source_component,source_record_id,idempotency_scope,idempotency_key,request_fingerprint,metadata)
            VALUES(:public,:tenant,:org,:series,:changed,:reason,:hash,CAST(:evidence AS JSONB),:occurred,:business_date,
            :calendar,:correlation,:causation,:actor_user,:actor_service,:component,:record,:scope,:key,:fingerprint,
            CAST(:metadata AS JSONB)) RETURNING id,public_id,request_fingerprint"""), {
            "public": str(command.public_id), "tenant": command.tenant_id, "org": command.organization_unit_id,
            "series": series_id, "changed": command.changed_from_at, "reason": command.cascade_reason,
            "hash": command.evidence_hash, "evidence": json.dumps(command.evidence_payload, sort_keys=True),
            "occurred": command.occurred_at, "business_date": command.business_date,
            "calendar": command.calendar_policy_version, "correlation": str(command.correlation_id),
            "causation": str(command.causation_id) if command.causation_id else None, "actor_user": command.actor_user_id,
            "actor_service": command.actor_service, "component": command.source_component, "record": command.source_record_id,
            "scope": command.idempotency_scope, "key": command.idempotency_key, "fingerprint": command.request_fingerprint,
            "metadata": json.dumps(command.metadata, sort_keys=True),
        }).mappings().one()
        return CascadeRunRecord(int(row["id"]), UUID(str(row["public_id"])), row["request_fingerprint"].strip(), False)

    @staticmethod
    def cascade_revision_ids(session, *, cascade_run_id):
        return tuple(int(value) for value in session.execute(text("""SELECT id FROM reconciliation_window_revisions
            WHERE cascade_run_id=:cascade ORDER BY reconciliation_window_id,revision_number"""), {"cascade": cascade_run_id}).scalars())
