"""SQLAlchemy repository for append-only canonical financial events."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Mapping
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from .event_contract import (
    ENGINE_CONTRACT,
    ENGINE_CONTRACT_VERSION,
    CanonicalFinancialEventCommand,
    CatalogEventPolicy,
    FinancialEventIdempotencyConflict,
    FinancialEventValidationError,
    canonical_command_fingerprint,
)


@dataclass(frozen=True)
class FinancialEventRecord:
    id: int
    public_id: UUID
    tenant_id: int
    organization_unit_id: int
    event_type_code: str
    event_version: int
    amount: Decimal
    currency_code: str
    economic_role: str
    source_record_id: int
    occurred_at: datetime
    recorded_at: datetime
    business_date: date
    calendar_policy_version: int
    idempotency_scope: str
    idempotency_key: str
    correlation_id: UUID
    classification_snapshot: Mapping[str, Any]
    posting_context: Mapping[str, Any]
    metadata: Mapping[str, Any]
    source_operational_account_id: int | None = None
    target_operational_account_id: int | None = None
    original_event_id: int | None = None
    actor_user_id: int | None = None
    actor_service: str | None = None
    causation_id: UUID | None = None
    evidence_hash: str | None = None
    replayed: bool = False

    @classmethod
    def from_row(
        cls, row: Mapping[str, Any], *, replayed: bool = False
    ) -> "FinancialEventRecord":
        values = dict(row)
        for name in ("public_id", "correlation_id", "causation_id"):
            if values.get(name) is not None:
                values[name] = UUID(str(values[name]))
        values["replayed"] = replayed
        return cls(**values)


_EVENT_COLUMNS = """
    id, public_id, tenant_id, organization_unit_id,
    event_type_code, event_version, amount, currency_code, economic_role,
    source_operational_account_id, target_operational_account_id,
    source_record_id, original_event_id, occurred_at, recorded_at,
    business_date, calendar_policy_version, actor_user_id, actor_service,
    idempotency_scope, idempotency_key, correlation_id, causation_id,
    classification_snapshot, posting_context, evidence_hash, metadata
"""

_FIND_IDEMPOTENT = text(
    f"""
    SELECT {_EVENT_COLUMNS}
    FROM public.financial_events
    WHERE tenant_id = :tenant_id
      AND idempotency_scope = :idempotency_scope
      AND idempotency_key = :idempotency_key
    """
)

_INSERT_EVENT = text(
    f"""
    INSERT INTO public.financial_events (
        public_id, tenant_id, organization_unit_id,
        event_type_code, event_version, amount, currency_code, economic_role,
        source_operational_account_id, target_operational_account_id,
        source_record_id, original_event_id, occurred_at, business_date,
        calendar_policy_version, actor_user_id, actor_service,
        idempotency_scope, idempotency_key, correlation_id, causation_id,
        classification_snapshot, posting_context, evidence_hash, metadata
    ) VALUES (
        :public_id, :tenant_id, :organization_unit_id,
        :event_type_code, :event_version, :amount, :currency_code, :economic_role,
        :source_operational_account_id, :target_operational_account_id,
        :source_record_id, :original_event_id, :occurred_at, :business_date,
        :calendar_policy_version, :actor_user_id, :actor_service,
        :idempotency_scope, :idempotency_key, :correlation_id, :causation_id,
        CAST(:classification_snapshot AS JSONB), CAST(:posting_context AS JSONB),
        :evidence_hash, CAST(:metadata AS JSONB)
    )
    RETURNING {_EVENT_COLUMNS}
    """
)


class CanonicalFinancialEventRepository:
    @staticmethod
    def load_catalog_policy(session, command: CanonicalFinancialEventCommand):
        row = session.execute(
            text(
                """
                SELECT event_type_code, event_version, amount_policy,
                       account_role_policy, definition_hash
                FROM public.financial_event_type_versions
                WHERE event_type_code = :event_type_code
                  AND event_version = :event_version
                  AND effective_from <= :occurred_at
                  AND (effective_to IS NULL OR effective_to > :occurred_at)
                """
            ),
            {
                "event_type_code": command.event_type_code,
                "event_version": command.event_version,
                "occurred_at": command.occurred_at,
            },
        ).mappings().one_or_none()
        if row is None:
            raise FinancialEventValidationError(
                "event_type_not_approved",
                "no effective approved catalog definition exists for the event",
            )
        return CatalogEventPolicy.from_database_row(row)

    @staticmethod
    def find_by_idempotency(
        session, command: CanonicalFinancialEventCommand
    ) -> FinancialEventRecord | None:
        row = session.execute(
            _FIND_IDEMPOTENT,
            {
                "tenant_id": command.tenant_id,
                "idempotency_scope": command.idempotency_scope,
                "idempotency_key": command.idempotency_key,
            },
        ).mappings().one_or_none()
        return FinancialEventRecord.from_row(row) if row else None

    @staticmethod
    def resolve_replay(
        record: FinancialEventRecord,
        command: CanonicalFinancialEventCommand,
    ) -> FinancialEventRecord:
        actual = (
            record.metadata.get("_kernel", {}).get("command_fingerprint")
            if isinstance(record.metadata, Mapping)
            else None
        )
        expected = canonical_command_fingerprint(command)
        if actual != expected:
            raise FinancialEventIdempotencyConflict(
                "idempotency_conflict",
                "idempotency identity already belongs to different event content",
            )
        return replace(record, replayed=True)

    @staticmethod
    def validate_references(
        session,
        command: CanonicalFinancialEventCommand,
        policy: CatalogEventPolicy,
    ) -> None:
        tenant_exists = session.execute(
            text("SELECT 1 FROM public.tenants WHERE id = :tenant_id"),
            {"tenant_id": command.tenant_id},
        ).scalar()
        if not tenant_exists:
            raise FinancialEventValidationError(
                "tenant_not_found", "tenant does not exist"
            )

        org = session.execute(
            text(
                """
                SELECT active
                FROM public.organization_units
                WHERE tenant_id = :tenant_id AND id = :organization_unit_id
                """
            ),
            {
                "tenant_id": command.tenant_id,
                "organization_unit_id": command.organization_unit_id,
            },
        ).mappings().one_or_none()
        if org is None or not org["active"]:
            raise FinancialEventValidationError(
                "organization_unit_not_active",
                "organization unit is missing, cross-tenant, or inactive",
            )

        currency = session.execute(
            text(
                """
                SELECT 1
                FROM public.currency_assets ca
                JOIN public.tenant_currency_policies tcp
                  ON tcp.currency_code = ca.code
                 AND tcp.tenant_id = :tenant_id
                WHERE ca.code = :currency_code
                  AND ca.active = TRUE
                  AND tcp.active = TRUE
                  AND tcp.effective_from <= :occurred_at
                  AND (tcp.effective_to IS NULL OR tcp.effective_to > :occurred_at)
                """
            ),
            {
                "tenant_id": command.tenant_id,
                "currency_code": command.currency_code,
                "occurred_at": command.occurred_at,
            },
        ).scalar()
        if not currency:
            raise FinancialEventValidationError(
                "currency_not_active_for_tenant",
                "currency is missing or has no effective tenant policy",
            )

        source = session.execute(
            text(
                """
                SELECT organization_unit_id, aggregate_type, retired_at
                FROM public.kernel_source_records
                WHERE tenant_id = :tenant_id AND id = :source_record_id
                """
            ),
            {
                "tenant_id": command.tenant_id,
                "source_record_id": command.source_record_id,
            },
        ).mappings().one_or_none()
        if source is None:
            raise FinancialEventValidationError(
                "source_record_not_found",
                "source record is missing or belongs to another tenant",
            )
        if source["retired_at"] is not None and source["retired_at"] <= command.occurred_at:
            raise FinancialEventValidationError(
                "source_record_retired", "source record was retired before the event"
            )
        if (
            source["organization_unit_id"] is not None
            and source["organization_unit_id"] != command.organization_unit_id
        ):
            raise FinancialEventValidationError(
                "source_organization_mismatch",
                "cross-organization source use requires explicit policy",
            )
        if source["aggregate_type"] not in policy.source_record_kinds:
            raise FinancialEventValidationError(
                "source_record_kind_not_allowed",
                "source record kind is not authoritative for this event type",
            )

        if command.actor_user_id is not None:
            actor = session.execute(
                text(
                    """
                    SELECT 1 FROM public.users
                    WHERE tenant_id = :tenant_id AND id = :actor_user_id
                      AND is_active = TRUE
                    """
                ),
                {
                    "tenant_id": command.tenant_id,
                    "actor_user_id": command.actor_user_id,
                },
            ).scalar()
            if not actor:
                raise FinancialEventValidationError(
                    "actor_not_active_for_tenant",
                    "actor user is missing, cross-tenant, or inactive",
                )

        for side, account_id in (
            ("source", command.source_operational_account_id),
            ("target", command.target_operational_account_id),
        ):
            if account_id is None:
                continue
            account = session.execute(
                text(
                    """
                    SELECT organization_unit_id, currency_code, active,
                           opened_at, closed_at
                    FROM public.operational_financial_accounts
                    WHERE tenant_id = :tenant_id AND id = :account_id
                    """
                ),
                {"tenant_id": command.tenant_id, "account_id": account_id},
            ).mappings().one_or_none()
            if account is None:
                raise FinancialEventValidationError(
                    "operational_account_not_found",
                    f"{side} account is missing or belongs to another tenant",
                )
            if (
                not account["active"]
                or account["opened_at"] > command.occurred_at
                or (
                    account["closed_at"] is not None
                    and account["closed_at"] <= command.occurred_at
                )
            ):
                raise FinancialEventValidationError(
                    "operational_account_not_active",
                    f"{side} account is not active at occurred_at",
                )
            if account["organization_unit_id"] != command.organization_unit_id:
                raise FinancialEventValidationError(
                    "account_organization_mismatch",
                    "cross-organization account use requires explicit policy",
                )
            if account["currency_code"] != command.currency_code:
                raise FinancialEventValidationError(
                    "account_currency_mismatch",
                    f"{side} account currency differs from event currency",
                )

        if command.original_event_id is not None:
            original = session.execute(
                text(
                    """
                    SELECT organization_unit_id, currency_code
                    FROM public.financial_events
                    WHERE tenant_id = :tenant_id AND id = :original_event_id
                    """
                ),
                {
                    "tenant_id": command.tenant_id,
                    "original_event_id": command.original_event_id,
                },
            ).mappings().one_or_none()
            if original is None:
                raise FinancialEventValidationError(
                    "original_event_not_found",
                    "original event is missing or belongs to another tenant",
                )
            if original["organization_unit_id"] != command.organization_unit_id:
                raise FinancialEventValidationError(
                    "original_event_organization_mismatch",
                    "cross-organization reversal requires explicit policy",
                )
            if original["currency_code"] != command.currency_code:
                raise FinancialEventValidationError(
                    "original_event_currency_mismatch",
                    "reversal currency must match the original event",
                )

    @staticmethod
    def insert(
        session, command: CanonicalFinancialEventCommand
    ) -> FinancialEventRecord:
        fingerprint = canonical_command_fingerprint(command)
        stored_metadata = dict(command.metadata)
        stored_metadata["_kernel"] = {
            "engine_contract": ENGINE_CONTRACT,
            "engine_contract_version": ENGINE_CONTRACT_VERSION,
            "command_fingerprint": fingerprint,
        }
        parameters = {
            **command.__dict__,
            "classification_snapshot": json.dumps(
                command.classification_snapshot,
                ensure_ascii=False,
                sort_keys=True,
            ),
            "posting_context": json.dumps(
                command.posting_context,
                ensure_ascii=False,
                sort_keys=True,
            ),
            "metadata": json.dumps(
                stored_metadata,
                ensure_ascii=False,
                sort_keys=True,
            ),
        }
        try:
            with session.begin_nested():
                row = session.execute(_INSERT_EVENT, parameters).mappings().one()
            return FinancialEventRecord.from_row(row)
        except IntegrityError as exc:
            existing = CanonicalFinancialEventRepository.find_by_idempotency(
                session, command
            )
            if existing is not None:
                return CanonicalFinancialEventRepository.resolve_replay(
                    existing, command
                )
            raise FinancialEventValidationError(
                "database_constraint_violation",
                "database rejected the canonical financial event",
            ) from exc
