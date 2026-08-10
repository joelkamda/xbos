"""Typed orchestration contracts for M5.0 receivables and customer balances."""

from __future__ import annotations

from dataclasses import dataclass

from .aging_contract import AsOfAgingQuery
from .allocation_contract import CreateValueSourceCommand
from .obligation_contract import CreateObligationCommand
from .value_application_contract import ApplyUnappliedValueCommand, ReceiveAndApplyValueCommand


CONTRACT_CODE = "XBOS_M50_RECEIVABLES_AND_CUSTOMER_BALANCES"
CONTRACT_VERSION = 1
RECEIVABLE_TYPES = frozenset({"trade_receivable", "customer_receivable"})
CUSTOMER_VALUE_TYPES = frozenset({"customer_credit", "customer_deposit", "customer_advance"})


class ReceivableLifecycleError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class OpenReceivableCommand:
    obligation: CreateObligationCommand

    def __post_init__(self) -> None:
        if self.obligation.obligation_type not in RECEIVABLE_TYPES:
            raise ReceivableLifecycleError(
                "invalid_receivable_type",
                "receivable orchestration accepts only approved receivable obligation types",
            )


@dataclass(frozen=True)
class ReceiveReceivablePaymentCommand:
    receipt: ReceiveAndApplyValueCommand

    def __post_init__(self) -> None:
        if self.receipt.value_source.source_type != "payment":
            raise ReceivableLifecycleError(
                "invalid_payment_source_type", "receivable payment must use the payment value-source type"
            )
        if self.receipt.application_batch is None:
            raise ReceivableLifecycleError(
                "payment_application_required", "receivable payment must identify at least one application target"
            )


@dataclass(frozen=True)
class IssueCustomerValueCommand:
    value_source: CreateValueSourceCommand

    def __post_init__(self) -> None:
        if self.value_source.source_type not in CUSTOMER_VALUE_TYPES:
            raise ReceivableLifecycleError(
                "invalid_customer_value_type", "customer value must be a credit, deposit, or advance"
            )
        if self.value_source.payment_settlement_public_id is not None:
            raise ReceivableLifecycleError(
                "customer_value_settlement_forbidden",
                "credit, deposit, and advance issuance cannot impersonate payment settlement evidence",
            )


@dataclass(frozen=True)
class ApplyCustomerValueCommand:
    application: ApplyUnappliedValueCommand


@dataclass(frozen=True)
class AgeReceivablesCommand:
    query: AsOfAgingQuery


def tenant_id(command) -> int:
    if isinstance(command, OpenReceivableCommand):
        return command.obligation.tenant_id
    if isinstance(command, ReceiveReceivablePaymentCommand):
        return command.receipt.value_source.tenant_id
    if isinstance(command, IssueCustomerValueCommand):
        return command.value_source.tenant_id
    if isinstance(command, ApplyCustomerValueCommand):
        return command.application.tenant_id
    if isinstance(command, AgeReceivablesCommand):
        return command.query.tenant_id
    raise ReceivableLifecycleError("unsupported_command", "unsupported receivable lifecycle command")
