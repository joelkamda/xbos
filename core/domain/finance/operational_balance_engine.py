"""Transactional M6.0 operational-account, anchor, and actual-balance authority."""

from __future__ import annotations

from .operational_balance_contract import (
    CreateOperationalAccountCommand,
    OperationalBalanceIdempotencyConflict,
    OperationalBalanceValidationError,
    RecordActualBalanceCommand,
    RecordBalanceAnchorCommand,
)
from .operational_balance_repository import OperationalBalanceRepository


class TransactionalOperationalBalanceEngine:
    repository = OperationalBalanceRepository

    @classmethod
    def create_account(cls, session, command: CreateOperationalAccountCommand):
        with session.begin_nested():
            replay = cls.repository.account_by_idempotency(session, command)
            if replay:
                if replay.request_fingerprint != command.request_fingerprint:
                    raise OperationalBalanceIdempotencyConflict("idempotency_conflict", "account idempotency identity has different content")
                return replay
            if cls.repository.account_by_public_id(session, tenant_id=command.tenant_id, public_id=command.public_id):
                raise OperationalBalanceValidationError("public_id_conflict", "operational account public id already exists")
            parent_id = None
            if command.parent_account_public_id:
                parent = cls.repository.account_by_public_id(
                    session, tenant_id=command.tenant_id, public_id=command.parent_account_public_id, lock=True
                )
                if parent is None:
                    raise OperationalBalanceValidationError("parent_not_found", "parent account does not exist in tenant scope")
                if parent.organization_unit_id != command.organization_unit_id or parent.currency_code != command.currency_code:
                    raise OperationalBalanceValidationError("parent_scope_mismatch", "parent organization or currency differs")
                if parent.aggregation_role != "parent_aggregate" or not parent.active:
                    raise OperationalBalanceValidationError("parent_not_eligible", "parent must be an active aggregate account")
                parent_id = parent.id
            return cls.repository.insert_account(session, command, parent_id)

    @classmethod
    def record_anchor(cls, session, command: RecordBalanceAnchorCommand):
        with session.begin_nested():
            replay = cls.repository.anchor_by_idempotency(session, command)
            if replay:
                if replay.request_fingerprint != command.request_fingerprint:
                    raise OperationalBalanceIdempotencyConflict("idempotency_conflict", "anchor idempotency identity has different content")
                return replay
            account = cls._account(session, command, lock=True)
            if cls.repository.account_has_anchor(session, tenant_id=command.tenant_id, account_id=account.id):
                raise OperationalBalanceValidationError("anchor_already_exists", "operational account has an immutable opening anchor")
            cls._validate_fact_time(account, command.anchor_at)
            return cls.repository.insert_anchor(session, command, account.id)

    @classmethod
    def record_actual(cls, session, command: RecordActualBalanceCommand):
        with session.begin_nested():
            replay = cls.repository.actual_by_idempotency(session, command)
            if replay:
                if replay.request_fingerprint != command.request_fingerprint:
                    raise OperationalBalanceIdempotencyConflict("idempotency_conflict", "actual-balance idempotency identity has different content")
                return replay
            account = cls._account(session, command, lock=True)
            if not cls.repository.account_has_anchor(session, tenant_id=command.tenant_id, account_id=account.id):
                raise OperationalBalanceValidationError("balance_anchor_required", "actual balance requires an opening anchor")
            cls._validate_fact_time(account, command.observed_at)
            return cls.repository.insert_actual(session, command, account.id)

    @classmethod
    def _account(cls, session, command, *, lock: bool):
        account = cls.repository.account_by_public_id(
            session, tenant_id=command.tenant_id, public_id=command.operational_account_public_id, lock=lock
        )
        if account is None:
            raise OperationalBalanceValidationError("account_not_found", "operational account does not exist in tenant scope")
        if account.organization_unit_id != command.organization_unit_id or account.currency_code != command.currency_code:
            raise OperationalBalanceValidationError("account_scope_mismatch", "account organization or currency differs")
        if account.aggregation_role != "leaf":
            raise OperationalBalanceValidationError("leaf_account_required", "balance facts require a leaf operational account")
        return account

    @staticmethod
    def _validate_fact_time(account, fact_at) -> None:
        if fact_at < account.opened_at or (account.closed_at is not None and fact_at > account.closed_at):
            raise OperationalBalanceValidationError("outside_account_lifetime", "balance fact falls outside account lifetime")
