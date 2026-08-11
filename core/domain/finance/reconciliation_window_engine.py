"""Transactional M6.2 reconciliation-window and correction-cascade authority."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo

from .operational_balance_repository import OperationalBalanceRepository
from .reconciliation_calendar_service import ReconciliationCalendarService
from .reconciliation_window_contract import (
    CascadeReconciliationWindowsCommand,
    CreateReconciliationCalendarPolicyCommand,
    CreateReconciliationSeriesCommand,
    RecordReconciliationWindowCommand,
    ReconciliationWindowValidationError,
)
from .reconciliation_window_repository import ReconciliationWindowRepository


@dataclass(frozen=True)
class RecordedReconciliationWindow:
    window: object
    revision: object


@dataclass(frozen=True)
class ReconciliationCascadeResult:
    cascade_run: object
    revision_ids: tuple[int, ...]


class TransactionalReconciliationWindowEngine:
    repository = ReconciliationWindowRepository
    balance_repository = OperationalBalanceRepository
    calendar_service = ReconciliationCalendarService

    @classmethod
    def create_calendar_policy(cls, session, command: CreateReconciliationCalendarPolicyCommand):
        with session.begin_nested():
            existing = cls.repository.policy_by_idempotency(session, command)
            if existing:
                cls._replay(existing.request_fingerprint, command.request_fingerprint)
                return existing
            return cls.repository.insert_policy(session, command)

    @classmethod
    def create_series(cls, session, command: CreateReconciliationSeriesCommand):
        with session.begin_nested():
            existing = cls.repository.series_by_idempotency(session, command)
            if existing:
                cls._replay(existing.request_fingerprint, command.request_fingerprint)
                return existing
            account = cls.balance_repository.account_by_public_id(
                session, tenant_id=command.tenant_id, public_id=command.operational_account_public_id, lock=True,
            )
            if account is None:
                raise ReconciliationWindowValidationError("account_not_found", "operational account is missing or cross-tenant")
            policy = cls.repository.policy_by_public_id(
                session, tenant_id=command.tenant_id, public_id=command.calendar_policy_public_id, lock=True,
            )
            if policy is None:
                raise ReconciliationWindowValidationError("calendar_policy_not_found", "calendar policy is missing or cross-tenant")
            if account.organization_unit_id != command.organization_unit_id or policy.organization_unit_id != command.organization_unit_id:
                raise ReconciliationWindowValidationError("organization_mismatch", "account, calendar, and series organization must match")
            if policy.policy_version != command.calendar_policy_version:
                raise ReconciliationWindowValidationError("calendar_policy_version_mismatch", "series calendar version differs from policy authority")
            if account.currency_code != command.currency_code:
                raise ReconciliationWindowValidationError("currency_mismatch", "series currency differs from operational account")
            if not account.active or account.aggregation_role != "leaf" or not account.reconciliation_enabled:
                raise ReconciliationWindowValidationError("account_not_reconcilable", "series requires an active reconciliation-enabled leaf account")
            if command.starts_at < account.opened_at or command.starts_at < policy.effective_from:
                raise ReconciliationWindowValidationError("series_precedes_authority", "series starts before account or calendar authority")
            local_clock = command.starts_at.astimezone(ZoneInfo(policy.timezone_name)).time().replace(tzinfo=None).isoformat(timespec="minutes")
            if local_clock not in {item["starts_at"] for item in policy.shifts}:
                raise ReconciliationWindowValidationError("series_not_shift_aligned", "series starts_at must be a configured shift boundary")
            return cls.repository.insert_series(session, command, account.id, policy.id)

    @classmethod
    def record_window(cls, session, command: RecordReconciliationWindowCommand) -> RecordedReconciliationWindow:
        with session.begin_nested():
            existing = cls.repository.window_by_idempotency(session, command)
            if existing:
                cls._replay(existing.request_fingerprint, command.request_fingerprint)
                revision = cls.repository.revision_by_number(
                    session, tenant_id=command.tenant_id, window_id=existing.id, revision_number=1,
                )
                return RecordedReconciliationWindow(existing, revision)
            series = cls.repository.series_by_public_id(
                session, tenant_id=command.tenant_id, public_id=command.reconciliation_series_public_id, lock=True,
            )
            if series is None:
                raise ReconciliationWindowValidationError("series_not_found", "reconciliation series is missing or cross-tenant")
            if series.organization_unit_id != command.organization_unit_id:
                raise ReconciliationWindowValidationError("series_organization_mismatch", "window and series organization differ")
            policy = cls.repository.policy_by_public_id(
                session, tenant_id=command.tenant_id,
                public_id=cls._policy_public_id(session, command.tenant_id, series.calendar_policy_id), lock=True,
            )
            if policy.policy_version != command.calendar_policy_version:
                raise ReconciliationWindowValidationError("calendar_policy_version_mismatch", "window calendar version differs from series policy")
            attribution = cls.calendar_service.validate_window(policy, command.window_start, command.window_end)
            predecessor = cls.repository.latest_window(session, tenant_id=command.tenant_id, series_id=series.id, lock=True)
            if predecessor is None:
                if command.window_start != series.starts_at:
                    raise ReconciliationWindowValidationError("first_window_must_start_series", "first window must start at series authority")
            elif predecessor.window_end != command.window_start:
                raise ReconciliationWindowValidationError("window_continuity_violation", "window must immediately follow its predecessor")
            projection = cls._projection(session, series, command.window_start, command.window_end)
            if predecessor:
                predecessor_revision = cls.repository.current_revision(
                    session, tenant_id=command.tenant_id, window_id=predecessor.id, lock=True,
                )
                if predecessor_revision.closing_expected != Decimal(projection["opening_expected"]):
                    raise ReconciliationWindowValidationError("predecessor_revision_stale", "cascade predecessor corrections before appending a window")
            actual = cls.repository.actual_in_window(
                session, tenant_id=command.tenant_id, account_id=series.operational_account_id,
                window_start=command.window_start, window_end=command.window_end,
            )
            window = cls.repository.insert_window(
                session, command, series, predecessor,
                business_date=attribution.business_date, shift_code=attribution.shift_code,
            )
            revision = cls.repository.insert_revision(
                session, public_id=cls._revision_public_id(window.public_id, 1), tenant_id=command.tenant_id,
                organization_unit_id=command.organization_unit_id, window_id=window.id, revision_number=1,
                revision_reason="initial", projection=projection, actual=actual,
                correlation_id=command.correlation_id, causation_id=command.causation_id,
                actor_user_id=command.actor_user_id, actor_service=command.actor_service,
                source_component=command.source_component, source_record_id=command.source_record_id,
                metadata={"window_evidence_hash": command.evidence_hash},
            )
            return RecordedReconciliationWindow(window, revision)

    @classmethod
    def cascade(cls, session, command: CascadeReconciliationWindowsCommand) -> ReconciliationCascadeResult:
        with session.begin_nested():
            existing = cls.repository.cascade_by_idempotency(session, command)
            if existing:
                cls._replay(existing.request_fingerprint, command.request_fingerprint)
                return ReconciliationCascadeResult(existing, cls.repository.cascade_revision_ids(session, cascade_run_id=existing.id))
            series = cls.repository.series_by_public_id(
                session, tenant_id=command.tenant_id, public_id=command.reconciliation_series_public_id, lock=True,
            )
            if series is None:
                raise ReconciliationWindowValidationError("series_not_found", "reconciliation series is missing or cross-tenant")
            if series.organization_unit_id != command.organization_unit_id:
                raise ReconciliationWindowValidationError("series_organization_mismatch", "cascade and series organization differ")
            if series.calendar_policy_version != command.calendar_policy_version:
                raise ReconciliationWindowValidationError("calendar_policy_version_mismatch", "cascade calendar version differs from series policy")
            run = cls.repository.insert_cascade(session, command, series.id)
            revisions: list[int] = []
            for row in cls.repository.windows_from(
                session, tenant_id=command.tenant_id, series_id=series.id, changed_from_at=command.changed_from_at,
            ):
                current = cls.repository.current_revision(session, tenant_id=command.tenant_id, window_id=int(row["id"]), lock=True)
                projection = cls._projection(session, series, row["window_start"], row["window_end"])
                actual = cls.repository.actual_in_window(
                    session, tenant_id=command.tenant_id, account_id=series.operational_account_id,
                    window_start=row["window_start"], window_end=row["window_end"],
                )
                actual_amount = Decimal(actual["actual_balance"]) if actual else None
                actual_id = int(actual["id"]) if actual else None
                if (current.opening_expected == Decimal(projection["opening_expected"])
                        and current.closing_expected == Decimal(projection["closing_expected"])
                        and current.actual_closing == actual_amount and current.actual_observation_id == actual_id):
                    continue
                revision_number = current.revision_number+1
                revision = cls.repository.insert_revision(
                    session, public_id=cls._revision_public_id(UUID(str(row["public_id"])), revision_number),
                    tenant_id=command.tenant_id, organization_unit_id=command.organization_unit_id,
                    window_id=int(row["id"]), revision_number=revision_number,
                    revision_reason="correction_cascade", projection=projection, actual=actual,
                    supersedes_revision_id=current.id, cascade_run_id=run.id,
                    correlation_id=command.correlation_id, causation_id=command.causation_id,
                    actor_user_id=command.actor_user_id, actor_service=command.actor_service,
                    source_component=command.source_component, source_record_id=command.source_record_id,
                    metadata={"cascade_reason": command.cascade_reason, "evidence_hash": command.evidence_hash},
                )
                revisions.append(revision.id)
            return ReconciliationCascadeResult(run, tuple(revisions))

    @classmethod
    def _projection(cls, session, series, window_start, window_end):
        opening = cls.balance_repository.position(
            session, tenant_id=series.tenant_id, organization_unit_id=series.organization_unit_id,
            account_id=series.operational_account_id, as_of=window_start,
        )
        closing = cls.balance_repository.position(
            session, tenant_id=series.tenant_id, organization_unit_id=series.organization_unit_id,
            account_id=series.operational_account_id, as_of=window_end,
        )
        if opening is None or closing is None:
            raise ReconciliationWindowValidationError("balance_authority_missing", "M6.0 balance authority cannot project this window")
        return {"opening_expected": Decimal(opening["expected_balance"]), "closing_expected": Decimal(closing["expected_balance"])}

    @staticmethod
    def _policy_public_id(session, tenant_id, policy_id):
        from sqlalchemy import text
        value = session.execute(text("SELECT public_id FROM reconciliation_calendar_policies WHERE tenant_id=:tenant AND id=:policy"), {
            "tenant": tenant_id, "policy": policy_id,
        }).scalar_one_or_none()
        if value is None:
            raise ReconciliationWindowValidationError("calendar_policy_not_found", "series calendar policy is missing")
        return UUID(str(value))

    @staticmethod
    def _revision_public_id(window_public_id: UUID, revision_number: int) -> UUID:
        return uuid5(NAMESPACE_URL, f"xbos:m62:window:{window_public_id}:revision:{revision_number}")

    @staticmethod
    def _replay(existing: str, requested: str) -> None:
        if existing != requested:
            raise ReconciliationWindowValidationError("idempotency_conflict", "idempotency identity was reused with different content")
