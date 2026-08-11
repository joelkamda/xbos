"""Transactional shared M6.4 reconciliation-control engine."""

from __future__ import annotations

from decimal import Decimal

from .operational_balance_contract import _fingerprint
from .reconciliation_control_contract import RecordReconciliationControlCommand, ReconciliationControlError
from .reconciliation_control_repository import ReconciliationControlRepository


class TransactionalReconciliationControlEngine:
    repository = ReconciliationControlRepository

    @classmethod
    def record(cls, session, command: RecordReconciliationControlCommand):
        with session.begin_nested():
            existing = cls.repository.by_idempotency(session, command)
            if existing:
                if existing.request_fingerprint != command.request_fingerprint:
                    raise ReconciliationControlError("idempotency_conflict", "idempotency identity was reused with different content")
                return existing
            period = cls.repository.resolve_period(session, command)
            if command.accounting_period_code and period is None:
                raise ReconciliationControlError("accounting_period_not_found", "accounting period is missing or cross-scope")
            if period and (command.period_start.date() < period["period_start"] or command.period_end.date() > period["period_end"]):
                raise ReconciliationControlError("accounting_period_mismatch", "control period is outside accounting period authority")
            authority = None
            if command.control_type == "bank":
                authority = cls.repository.bank_authority(session, command)
                if authority is None:
                    raise ReconciliationControlError("bank_scope_not_found", "bank account/window authority is missing or cross-tenant")
                if int(authority["organization_unit_id"]) != command.organization_unit_id:
                    raise ReconciliationControlError("organization_mismatch", "bank account organization differs")
                if authority["currency_code"] != command.currency_code:
                    raise ReconciliationControlError("currency_mismatch", "bank account currency differs")
                if authority["window_start"] != command.period_start or authority["window_end"] != command.period_end or command.as_of != command.period_end:
                    raise ReconciliationControlError("window_period_mismatch", "bank control must match its governed window exactly")
                position = cls.repository.bank_position(session, command, authority)
                if position is None:
                    raise ReconciliationControlError("canonical_position_unavailable", "bank account has no balance anchor for the period")
            else:
                position = cls.repository.party_position(session, command)
            latest = cls.repository.latest(session, command)
            explained = sum((item.amount for item in command.explanations), Decimal("0"))
            raw = command.control_position - position.closing
            unexplained = raw - explained
            status = "balanced" if raw == 0 else ("explained" if unexplained == 0 else "exception")
            semantic = _fingerprint({
                "control_type": command.control_type, "tenant_id": command.tenant_id,
                "organization_unit_id": command.organization_unit_id, "currency_code": command.currency_code,
                "period_start": command.period_start.isoformat(), "period_end": command.period_end.isoformat(),
                "as_of": command.as_of.isoformat(), "opening": str(position.opening),
                "increases": str(position.increases), "decreases": str(position.decreases),
                "adjustments": str(position.adjustments), "closing": str(position.closing),
                "control_position": str(command.control_position), "explained": str(explained),
                "unexplained": str(unexplained), "status": status,
                "evidence": [item.canonical_payload() for item in command.evidence],
                "explanations": [item.canonical_payload() for item in command.explanations],
            })
            return cls.repository.insert(session, command, position, authority, period, latest, semantic,
                                         explained, raw, unexplained, status)
