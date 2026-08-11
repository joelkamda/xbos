"""Transactional M6.3 formal-close and governed-reopen authority."""

from __future__ import annotations

from decimal import Decimal

from .reconciliation_close_contract import (
    CloseReconciliationWindowCommand,
    ReconciliationCloseValidationError,
    ReopenReconciliationWindowCommand,
)
from .reconciliation_close_repository import ReconciliationCloseRepository


class TransactionalReconciliationCloseEngine:
    repository = ReconciliationCloseRepository

    @classmethod
    def close(cls, session, command: CloseReconciliationWindowCommand):
        with session.begin_nested():
            existing = cls.repository.by_idempotency(session, command)
            if existing:
                cls._replay(existing.request_fingerprint, command.request_fingerprint)
                return existing
            authority = cls._authority(session, command)
            latest = cls.repository.latest(session, tenant_id=command.tenant_id, window_id=int(authority["window_id"]), lock=True)
            if latest and latest.transition_type != "reopen":
                raise ReconciliationCloseValidationError("window_already_closed", "window is already formally closed")
            predecessor = cls.repository.predecessor_latest(
                session, tenant_id=command.tenant_id, predecessor_window_id=authority["predecessor_window_id"],
            )
            if authority["predecessor_window_id"] is not None and (predecessor is None or predecessor.transition_type != "close"):
                raise ReconciliationCloseValidationError("predecessor_not_closed", "required predecessor must be formally closed")
            if authority["readiness_condition"] != "ready":
                raise ReconciliationCloseValidationError("window_not_ready", "current reconciliation revision is not ready")
            variance = Decimal(authority["variance"])
            if command.close_disposition == "balanced" and variance != 0:
                raise ReconciliationCloseValidationError("balanced_disposition_requires_zero_variance", "balanced close requires zero variance")
            if command.close_disposition != "balanced" and variance == 0:
                raise ReconciliationCloseValidationError("variance_disposition_requires_variance", "variance disposition requires non-zero variance")
            return cls.repository.insert(session, command, authority, transition_type="close", prior_event=latest)

    @classmethod
    def reopen(cls, session, command: ReopenReconciliationWindowCommand):
        with session.begin_nested():
            existing = cls.repository.by_idempotency(session, command)
            if existing:
                cls._replay(existing.request_fingerprint, command.request_fingerprint)
                return existing
            authority = cls._authority(session, command)
            latest = cls.repository.latest(session, tenant_id=command.tenant_id, window_id=int(authority["window_id"]), lock=True)
            if latest is None or latest.transition_type != "close" or latest.public_id != command.prior_close_public_id:
                raise ReconciliationCloseValidationError("prior_close_mismatch", "reopen must link the current formal close")
            if cls.repository.user_in_tenant(session, tenant_id=command.tenant_id, user_id=command.approved_by_user_id) is None:
                raise ReconciliationCloseValidationError("approval_authority_not_found", "approver is missing or cross-tenant")
            return cls.repository.insert(
                session, command, authority, transition_type="reopen", prior_event=latest,
                approved_by=command.approved_by_user_id, approved_at=command.approved_at,
            )

    @classmethod
    def _authority(cls, session, command):
        authority = cls.repository.authority(session, command)
        if authority is None:
            raise ReconciliationCloseValidationError("window_not_found", "window is missing or cross-tenant")
        if int(authority["organization_unit_id"]) != command.organization_unit_id:
            raise ReconciliationCloseValidationError("organization_mismatch", "window and command organization differ")
        if int(authority["calendar_policy_version"]) != command.calendar_policy_version:
            raise ReconciliationCloseValidationError("calendar_policy_version_mismatch", "window calendar authority differs")
        if authority["business_date"] != command.business_date:
            raise ReconciliationCloseValidationError("business_date_mismatch", "window business-date authority differs")
        if int(authority["revision_number"]) != command.governed_revision_number:
            raise ReconciliationCloseValidationError("stale_revision", "transition must target the current reconciliation revision")
        if authority["period_code"] is None or authority["period_code"] != command.accounting_period_code:
            raise ReconciliationCloseValidationError("accounting_period_mismatch", "exact covering accounting period is required")
        if authority["period_state"] not in {"open", "reopened"}:
            raise ReconciliationCloseValidationError("accounting_period_not_open", "accounting period must be open or separately reopened")
        return authority

    @staticmethod
    def _replay(existing: str, requested: str) -> None:
        if existing != requested:
            raise ReconciliationCloseValidationError("idempotency_conflict", "idempotency identity was reused with different content")
