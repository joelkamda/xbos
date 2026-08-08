"""Tenant-scoped, SELECT-only persistence for canonical financial traces."""

from __future__ import annotations

from typing import Any, Mapping

from sqlalchemy import text

from .trace_contract import FinancialEventTraceQuery


class CanonicalFinancialTraceRepository:
    """Load persisted truth without locking or mutating financial records."""

    @staticmethod
    def load_event(session, query: FinancialEventTraceQuery) -> Mapping[str, Any] | None:
        row = session.execute(
            text(
                """
                SELECT event.id, event.public_id, event.tenant_id,
                       event.organization_unit_id, unit.public_id AS organization_unit_public_id,
                       unit.code AS organization_unit_code, unit.name AS organization_unit_name,
                       unit.unit_type AS organization_unit_type,
                       event.event_type_code, event.event_version,
                       event.amount, event.currency_code, event.economic_role,
                       event.source_operational_account_id,
                       event.target_operational_account_id,
                       event.source_record_id, event.original_event_id,
                       original.public_id AS original_event_public_id,
                       event.occurred_at, event.recorded_at, event.business_date,
                       event.calendar_policy_version, event.actor_user_id,
                       event.actor_service, event.idempotency_scope,
                       event.idempotency_key, event.correlation_id,
                       event.causation_id, event.classification_snapshot,
                       event.posting_context, event.evidence_hash, event.metadata,
                       catalog.display_name AS event_display_name,
                       catalog.definition AS event_definition,
                       catalog.reconciliation_effect,
                       catalog.posting_eligible,
                       catalog.definition_hash AS catalog_definition_hash
                FROM public.financial_events event
                JOIN public.organization_units unit
                  ON unit.tenant_id = event.tenant_id
                 AND unit.id = event.organization_unit_id
                JOIN public.financial_event_type_versions catalog
                  ON catalog.event_type_code = event.event_type_code
                 AND catalog.event_version = event.event_version
                LEFT JOIN public.financial_events original
                  ON original.tenant_id = event.tenant_id
                 AND original.id = event.original_event_id
                WHERE event.tenant_id = :tenant_id
                  AND event.public_id = :event_public_id
                """
            ),
            {"tenant_id": query.tenant_id, "event_public_id": query.event_public_id},
        ).mappings().one_or_none()
        return dict(row) if row else None

    @staticmethod
    def load_source(session, *, tenant_id: int, source_record_id: int) -> Mapping[str, Any] | None:
        row = session.execute(
            text(
                """
                SELECT source.public_id, source.tenant_id,
                       source.organization_unit_id, source.source_component,
                       source.aggregate_type, source.aggregate_external_id,
                       source.aggregate_version, source.source_occurred_at,
                       source.registered_at, source.retired_at, source.metadata
                FROM public.kernel_source_records source
                WHERE source.tenant_id = :tenant_id
                  AND source.id = :source_record_id
                """
            ),
            {"tenant_id": tenant_id, "source_record_id": source_record_id},
        ).mappings().one_or_none()
        return dict(row) if row else None

    @staticmethod
    def load_idempotency(
        session, *, tenant_id: int, scope: str, idempotency_key: str
    ) -> Mapping[str, Any] | None:
        row = session.execute(
            text(
                """
                SELECT record.tenant_id, record.scope, record.idempotency_key,
                       record.request_fingerprint, record.processing_state,
                       record.response_code, record.response_snapshot,
                       record.created_at, record.completed_at, record.expires_at
                FROM public.idempotency_records record
                WHERE record.tenant_id = :tenant_id
                  AND record.scope = :idempotency_scope
                  AND record.idempotency_key = :idempotency_key
                """
            ),
            {
                "tenant_id": tenant_id,
                "idempotency_scope": scope,
                "idempotency_key": idempotency_key,
            },
        ).mappings().one_or_none()
        return dict(row) if row else None

    @staticmethod
    def load_outbox(
        session, *, tenant_id: int, event_public_id
    ) -> Mapping[str, Any] | None:
        row = session.execute(
            text(
                """
                SELECT message.public_id, message.tenant_id,
                       message.organization_unit_id,
                       message.source_event_public_id, message.topic,
                       message.message_key, message.event_name,
                       message.event_version, message.payload_hash,
                       message.delivery_state, message.available_at,
                       message.created_at, message.published_at,
                       message.delivery_attempts, message.last_error,
                       message.occurred_at, message.recorded_at,
                       message.correlation_id, message.causation_id
                FROM public.outbox_messages message
                WHERE message.tenant_id = :tenant_id
                  AND message.source_event_public_id = :event_public_id
                """
            ),
            {"tenant_id": tenant_id, "event_public_id": event_public_id},
        ).mappings().one_or_none()
        return dict(row) if row else None

    @staticmethod
    def load_posting(
        session, *, tenant_id: int, event_id: int
    ) -> Mapping[str, Any] | None:
        entries = session.execute(
            text(
                """
                SELECT entry.id, entry.public_id, entry.tenant_id,
                       entry.legal_entity_unit_id, entry.accounting_period_id,
                       period.period_code, period.period_state,
                       entry.journal_code, entry.entry_number, entry.entry_state,
                       entry.transaction_currency_code, entry.base_currency_code,
                       entry.posting_date, entry.business_date,
                       entry.description, entry.posting_profile_code,
                       entry.correlation_id, entry.created_at, entry.posted_at,
                       link.source_amount, link.allocation_role
                FROM public.journal_entry_event_links link
                JOIN public.journal_entries entry
                  ON entry.tenant_id = link.tenant_id
                 AND entry.id = link.journal_entry_id
                JOIN public.accounting_periods period
                  ON period.tenant_id = entry.tenant_id
                 AND period.id = entry.accounting_period_id
                WHERE link.tenant_id = :tenant_id
                  AND link.financial_event_id = :event_id
                  AND link.allocation_role = 'primary_event_posting'
                ORDER BY entry.id
                LIMIT 2
                """
            ),
            {"tenant_id": tenant_id, "event_id": event_id},
        ).mappings().all()
        if not entries:
            return None
        if len(entries) != 1:
            return {"ambiguous_primary_entries": len(entries), "lines": []}
        entry = dict(entries[0])
        lines = session.execute(
            text(
                """
                SELECT line.line_number, line.tenant_id, line.account_role,
                       line.transaction_currency_code,
                       line.transaction_debit_amount,
                       line.transaction_credit_amount,
                       line.base_currency_code, line.base_debit_amount,
                       line.base_credit_amount, line.fx_rate,
                       line.dimension_snapshot,
                       account.public_id AS ledger_account_public_id,
                       account.account_code, account.account_name,
                       account.account_type, account.normal_balance
                FROM public.journal_lines line
                JOIN public.ledger_accounts account
                  ON account.tenant_id = line.tenant_id
                 AND account.id = line.ledger_account_id
                WHERE line.tenant_id = :tenant_id
                  AND line.journal_entry_id = :journal_entry_id
                ORDER BY line.line_number
                """
            ),
            {"tenant_id": tenant_id, "journal_entry_id": entry["id"]},
        ).mappings().all()
        entry.pop("id", None)
        entry["lines"] = [dict(line) for line in lines]
        return entry

    @staticmethod
    def load_correction_lineage(
        session, *, tenant_id: int, event_id: int
    ) -> tuple[Mapping[str, Any], ...]:
        rows = session.execute(
            text(
                """
                WITH RECURSIVE ancestors AS (
                    SELECT event.id, event.public_id, event.original_event_id,
                           event.event_type_code, event.amount,
                           event.currency_code, event.business_date, 0 AS depth
                    FROM public.financial_events event
                    WHERE event.tenant_id = :tenant_id AND event.id = :event_id
                    UNION ALL
                    SELECT parent.id, parent.public_id, parent.original_event_id,
                           parent.event_type_code, parent.amount,
                           parent.currency_code, parent.business_date,
                           ancestors.depth - 1
                    FROM public.financial_events parent
                    JOIN ancestors ON ancestors.original_event_id = parent.id
                    WHERE parent.tenant_id = :tenant_id
                ), descendants AS (
                    SELECT event.id, event.public_id, event.original_event_id,
                           event.event_type_code, event.amount,
                           event.currency_code, event.business_date, 0 AS depth
                    FROM public.financial_events event
                    WHERE event.tenant_id = :tenant_id AND event.id = :event_id
                    UNION ALL
                    SELECT child.id, child.public_id, child.original_event_id,
                           child.event_type_code, child.amount,
                           child.currency_code, child.business_date,
                           descendants.depth + 1
                    FROM public.financial_events child
                    JOIN descendants ON child.original_event_id = descendants.id
                    WHERE child.tenant_id = :tenant_id
                )
                SELECT public_id, event_type_code, amount, currency_code,
                       business_date, depth,
                       CASE WHEN depth < 0 THEN 'ancestor'
                            WHEN depth = 0 THEN 'selected'
                            ELSE 'correction' END AS relationship
                FROM (
                    SELECT * FROM ancestors
                    UNION
                    SELECT * FROM descendants
                ) lineage
                ORDER BY depth, public_id
                """
            ),
            {"tenant_id": tenant_id, "event_id": event_id},
        ).mappings().all()
        return tuple(dict(row) for row in rows)

    @staticmethod
    def load_correlation_peers(
        session, *, tenant_id: int, correlation_id, selected_event_id: int
    ) -> tuple[Mapping[str, Any], ...]:
        rows = session.execute(
            text(
                """
                SELECT event.public_id, event.event_type_code,
                       event.event_version, event.amount, event.currency_code,
                       event.business_date, event.occurred_at
                FROM public.financial_events event
                WHERE event.tenant_id = :tenant_id
                  AND event.correlation_id = :correlation_id
                  AND event.id <> :selected_event_id
                ORDER BY event.occurred_at, event.id
                """
            ),
            {
                "tenant_id": tenant_id,
                "correlation_id": correlation_id,
                "selected_event_id": selected_event_id,
            },
        ).mappings().all()
        return tuple(dict(row) for row in rows)
