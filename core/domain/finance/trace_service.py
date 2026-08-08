"""Deterministic explanation service over immutable canonical finance truth."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from .trace_contract import (
    FinancialEventTrace,
    FinancialEventTraceQuery,
    FinancialTraceIntegrityError,
    FinancialTraceNotFound,
)
from .trace_repository import CanonicalFinancialTraceRepository


class CanonicalFinancialTraceService:
    repository = CanonicalFinancialTraceRepository

    @classmethod
    def explain(
        cls, session, query: FinancialEventTraceQuery
    ) -> FinancialEventTrace:
        event = cls.repository.load_event(session, query)
        if event is None:
            raise FinancialTraceNotFound(
                "financial_event_not_found",
                "financial event was not found in the authorized tenant scope",
            )
        if int(event["tenant_id"]) != query.tenant_id:
            raise FinancialTraceIntegrityError(
                "tenant_scope_violation", "repository returned cross-tenant financial truth"
            )

        source = cls.repository.load_source(
            session,
            tenant_id=query.tenant_id,
            source_record_id=int(event["source_record_id"]),
        )
        if source is None:
            raise FinancialTraceIntegrityError(
                "source_record_missing", "financial event source record is missing"
            )
        idempotency = cls.repository.load_idempotency(
            session,
            tenant_id=query.tenant_id,
            scope=str(event["idempotency_scope"]),
            idempotency_key=str(event["idempotency_key"]),
        )
        outbox = cls.repository.load_outbox(
            session,
            tenant_id=query.tenant_id,
            event_public_id=query.event_public_id,
        )
        posting = cls.repository.load_posting(
            session, tenant_id=query.tenant_id, event_id=int(event["id"])
        )
        lineage = cls.repository.load_correction_lineage(
            session, tenant_id=query.tenant_id, event_id=int(event["id"])
        )
        peers = cls.repository.load_correlation_peers(
            session,
            tenant_id=query.tenant_id,
            correlation_id=event["correlation_id"],
            selected_event_id=int(event["id"]),
        )

        cls._assert_tenant_scope(
            query.tenant_id, source, idempotency, outbox, posting
        )

        public_event = cls._public_event(event)
        public_source = cls._without_internal_ids(source)
        public_posting = cls._public_posting(posting)
        integrity = cls._integrity(event, idempotency, outbox, posting, lineage)
        explanation = cls._explanation(
            public_event, public_source, idempotency, outbox, public_posting, lineage
        )
        return FinancialEventTrace(
            query=query,
            event=public_event,
            source=public_source,
            idempotency=cls._without_internal_ids(idempotency),
            outbox=cls._without_internal_ids(outbox),
            posting=public_posting,
            correction_lineage=tuple(cls._without_internal_ids(row) for row in lineage),
            correlation_peers=tuple(cls._without_internal_ids(row) for row in peers),
            integrity=integrity,
            explanation=explanation,
        )

    @staticmethod
    def _without_internal_ids(value):
        if value is None:
            return None
        return {
            key: item
            for key, item in dict(value).items()
            if key not in {"id", "source_record_id", "original_event_id"}
        }

    @staticmethod
    def _assert_tenant_scope(tenant_id: int, *sections) -> None:
        for section in sections:
            if section is None:
                continue
            if "tenant_id" in section and int(section["tenant_id"]) != tenant_id:
                raise FinancialTraceIntegrityError(
                    "tenant_scope_violation",
                    "repository returned cross-tenant financial truth",
                )
            for line in section.get("lines", ()):
                if "tenant_id" in line and int(line["tenant_id"]) != tenant_id:
                    raise FinancialTraceIntegrityError(
                        "tenant_scope_violation",
                        "repository returned a cross-tenant journal line",
                    )

    @classmethod
    def _public_event(cls, event: Mapping[str, Any]) -> Mapping[str, Any]:
        hidden = {
            "id",
            "tenant_id",
            "source_record_id",
            "original_event_id",
            "source_operational_account_id",
            "target_operational_account_id",
        }
        return {key: value for key, value in event.items() if key not in hidden}

    @classmethod
    def _public_posting(cls, posting):
        if posting is None:
            return None
        result = cls._without_internal_ids(posting)
        result["lines"] = [cls._without_internal_ids(line) for line in posting.get("lines", [])]
        return result

    @staticmethod
    def _integrity(event, idempotency, outbox, posting, lineage):
        posting_eligible = bool(event["posting_eligible"])
        ambiguous = bool(posting and posting.get("ambiguous_primary_entries"))
        lines = posting.get("lines", []) if posting and not ambiguous else []
        transaction_debits = sum(
            (Decimal(str(line["transaction_debit_amount"])) for line in lines), Decimal("0")
        )
        transaction_credits = sum(
            (Decimal(str(line["transaction_credit_amount"])) for line in lines), Decimal("0")
        )
        base_debits = sum(
            (Decimal(str(line["base_debit_amount"])) for line in lines), Decimal("0")
        )
        base_credits = sum(
            (Decimal(str(line["base_credit_amount"])) for line in lines), Decimal("0")
        )
        selected_count = sum(row.get("relationship") == "selected" for row in lineage)
        checks = {
            "catalog_definition_resolved": bool(event.get("catalog_definition_hash")),
            "source_record_resolved": True,
            "idempotency_completed": bool(
                idempotency and idempotency.get("processing_state") == "completed"
            ),
            "idempotency_identity_matches_event": bool(
                idempotency
                and idempotency.get("scope") == event["idempotency_scope"]
                and idempotency.get("idempotency_key") == event["idempotency_key"]
            ),
            "outbox_present": outbox is not None,
            "outbox_identity_matches_event": bool(
                outbox
                and str(outbox.get("source_event_public_id")) == str(event["public_id"])
                and outbox.get("event_name") == event["event_type_code"]
                and int(outbox.get("event_version", 0)) == int(event["event_version"])
            ),
            "primary_posting_cardinality_valid": not ambiguous,
            "posting_presence_matches_catalog": (posting is not None) == posting_eligible,
            "transaction_currency_balanced": bool(lines) and transaction_debits == transaction_credits
            if posting_eligible else posting is None,
            "base_currency_balanced": bool(lines) and base_debits == base_credits
            if posting_eligible else posting is None,
            "correction_lineage_has_one_selected_event": selected_count == 1,
            "original_link_resolved": (
                event.get("original_event_id") is None
                or event.get("original_event_public_id") is not None
            ),
        }
        return {
            "status": "PASS" if all(checks.values()) else "FAIL",
            "checks": checks,
            "transaction_debits": transaction_debits,
            "transaction_credits": transaction_credits,
            "base_debits": base_debits,
            "base_credits": base_credits,
        }

    @staticmethod
    def _explanation(event, source, idempotency, outbox, posting, lineage):
        if posting is None:
            posting_summary = "The catalog marks this event as non-posting; no journal was created."
        elif posting.get("ambiguous_primary_entries"):
            posting_summary = "Persisted truth contains multiple authoritative primary journals."
        else:
            posting_summary = (
                f"Profile {posting['posting_profile_code']} posted "
                f"{len(posting.get('lines', []))} immutable journal lines."
            )
        correction_count = sum(row.get("relationship") == "correction" for row in lineage)
        return {
            "what_happened": (
                f"{event['event_display_name']} recorded {event['amount']} "
                f"{event['currency_code']} for business date {event['business_date']}."
            ),
            "why_it_exists": (
                f"Source component {source['source_component']} registered "
                f"{source['aggregate_type']} {source['aggregate_external_id']}."
            ),
            "how_it_posted": posting_summary,
            "delivery": (
                f"Transactional delivery is {outbox['delivery_state']}."
                if outbox else "No transactional outbox message was found."
            ),
            "idempotency": (
                f"Command identity is {idempotency['processing_state']}."
                if idempotency else "No command-idempotency record was found."
            ),
            "corrections": f"{correction_count} descendant correction event(s) are linked.",
            "authority": "Persisted immutable facts and snapshots are authoritative; this explanation is derived and read-only.",
        }
