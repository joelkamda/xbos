"""Typed M5.1 payable and governed-disbursement orchestration contracts."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from .obligation_contract import CreateObligationCommand
from .value_application_contract import ApplyUnappliedValueCommand, ReceiveAndApplyValueCommand


CONTRACT_CODE = "XBOS_M51_PAYABLES_AND_GOVERNED_DISBURSEMENTS"
CONTRACT_VERSION = 1
PAYABLE_TYPES = frozenset({"trade_payable", "supplier_payable", "expense_payable"})
DISBURSEMENT_SOURCE_TYPE = "disbursement"
PAYEE_METADATA_KEY = "payee_party_id"


class PayableLifecycleError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _payee(metadata) -> UUID:
    value = metadata.get(PAYEE_METADATA_KEY) if hasattr(metadata, "get") else None
    try:
        selected = UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise PayableLifecycleError(
            "payee_identity_required", "disbursement metadata must contain a valid payee_party_id"
        ) from exc
    if selected.int == 0:
        raise PayableLifecycleError("payee_identity_required", "payee_party_id cannot be nil")
    return selected


@dataclass(frozen=True)
class OpenPayableCommand:
    obligation: CreateObligationCommand

    def __post_init__(self) -> None:
        if self.obligation.obligation_type not in PAYABLE_TYPES:
            raise PayableLifecycleError(
                "invalid_payable_type", "payable orchestration accepts only approved payable obligation types"
            )


@dataclass(frozen=True)
class DisbursePayablesCommand:
    disbursement: ReceiveAndApplyValueCommand

    def __post_init__(self) -> None:
        source = self.disbursement.value_source
        if source.source_type != DISBURSEMENT_SOURCE_TYPE:
            raise PayableLifecycleError(
                "invalid_disbursement_type", "governed payable value must use the disbursement source type"
            )
        if source.payment_settlement_public_id is None:
            raise PayableLifecycleError(
                "outgoing_settlement_required", "disbursement must reference outgoing settlement authority"
            )
        if self.disbursement.application_batch is None:
            raise PayableLifecycleError(
                "disbursement_application_required", "disbursement must identify at least one payable"
            )
        _payee(source.metadata)

    @property
    def payee_party_id(self) -> UUID:
        return _payee(self.disbursement.value_source.metadata)


@dataclass(frozen=True)
class ApplyDisbursementCommand:
    application: ApplyUnappliedValueCommand
